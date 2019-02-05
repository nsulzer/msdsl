import numpy as np
import scipy.linalg

from typing import List
from scipy.signal import cont2discrete
from collections import OrderedDict
from itertools import chain
from enum import Enum, auto

from msdsl.generator import CodeGenerator
from msdsl.expr import (Constant, AnalogInput, AnalogOutput, DigitalInput, DigitalOutput, Signal, AnalogSignal,
                        ModelExpr, AnalogArray, DigitalArray)
from msdsl.eqnsys import eqn_sys_to_lds

class AssignmentType(Enum):
    THIS_CYCLE = auto()
    NEXT_CYCLE = auto()

class Assignment:
    def __init__(self, signal: Signal, expr: ModelExpr, assignment_type: AssignmentType):
        self.signal = signal
        self.expr = expr
        self.assignment_type = assignment_type

class MixedSignalModel:
    def __init__(self, name, *ios, dt=None):
        # save settings
        self.name = name
        self.dt = dt

        # add ios
        self.signals = OrderedDict()
        for io in ios:
            self.add_signal(io)

        # add clock and reset pins
        self.add_signal(DigitalInput('clk'))
        self.add_signal(DigitalInput('rst'))

        # expressions used to assign internal and external signals
        self.assignments = []

        # probe signals
        self.probes = []

    def __getattr__(self, item):
        return self.signals[item]

    def add_signal(self, signal: Signal):
        self.signals[signal.name] = signal

    def add_probe(self, signal: Signal):
        self.probes.append(signal)

    def add_eqn_sys(self, eqns=None, internals=None, inputs=None, states=None, outputs=None):
        A, B, C, D = eqn_sys_to_lds(eqns=eqns, internals=internals, inputs=inputs, states=states, outputs=outputs)

        self.add_lds(sys=(A, B, C, D), inputs=inputs, states=states, outputs=outputs)

    def add_lds(self, sys, inputs=None, states=None, outputs=None):
        # extract matrices
        A, B, C, D = sys

        # compute coefficients
        A_tilde = scipy.linalg.expm(self.dt*A)
        B_tilde = np.linalg.solve(A, (A_tilde-np.eye(*A.shape)).dot(B))

        # add discrete-time equation for state update
        sys_tilde = (A_tilde, B_tilde, C, D)
        self.add_discrete_time_eqn(sys_tilde, inputs=inputs, states=states, outputs=outputs)

    def add_discrete_time_eqn(self, sys, inputs=None, states=None, outputs=None):
        # set defaults
        inputs = inputs if inputs is not None else []
        states = states if states is not None else []
        outputs = outputs if outputs is not None else []

        # extract matrices
        A, B, C, D = sys

        # state updates
        for row, _ in enumerate(states):
            expr = 0
            for col, _ in enumerate(states):
                expr = expr + float(A[row, col])*states[col]
            for col, _ in enumerate(inputs):
                expr = expr + float(B[row, col])*inputs[col]
            self.set_next_cycle(states[row], expr)

        # output updates
        for row, _ in enumerate(outputs):
            expr = 0
            for col, _ in enumerate(states):
                expr = expr + float(C[row, col])*states[col]
            for col, _ in enumerate(inputs):
                expr = expr + float(D[row, col])*inputs[col]
            self.set_this_cycle(outputs[row], expr)

    def set_next_cycle(self, signal: Signal, expr: ModelExpr):
        self.assignments.append(Assignment(signal, expr, AssignmentType.NEXT_CYCLE))

    def set_this_cycle(self, signal: Signal, expr: ModelExpr):
        self.assignments.append(Assignment(signal, expr, AssignmentType.THIS_CYCLE))

    def discretize_diff_eq(self, signal: Signal, deriv_expr: ModelExpr):
        return self.dt*deriv_expr + signal

    def set_deriv(self, signal: Signal, deriv_expr: ModelExpr):
        self.set_next_cycle(signal, self.discretize_diff_eq(signal, deriv_expr))

    def set_dynamics_cases(self, signal: Signal, cases: List, addr: ModelExpr):
        # create list of potential values to be assigned to signal in the next cycle
        terms = []
        for type, case_expr in cases:
            if type == 'diff_eq':
                term = self.discretize_diff_eq(signal, case_expr)
            elif type == 'equals':
                term = case_expr
            else:
                raise Exception('Invalid dynamics type.')

            terms.append(term)

        # assign the appropriate value to signal
        self.set_next_cycle(signal, AnalogArray(terms, addr))

    def set_state_machine(self, signal: Signal, cases: List):
        self.set_next_cycle(signal, DigitalArray(cases, signal))

    def set_tf(self, output, input_, tf):
        # discretize transfer function
        res = cont2discrete(tf, self.dt)

        # get numerator and denominator coefficients
        b = [+float(val) for val in res[0].flatten()]
        a = [-float(val) for val in res[1].flatten()]

        # create input and output histories
        i_hist = self.make_analog_history(input_, len(b))
        o_hist = self.make_analog_history(output, len(a))

        # implement the filter
        expr = Constant(0)
        for coeff, var in chain(zip(b, i_hist), zip(a[1:], o_hist)):
            expr += coeff*var

        self.set_next_cycle(output, expr)

    def make_analog_history(self, first: AnalogSignal, length: int):
        hist = []

        for k in range(length):
            if k == 0:
                hist.append(first)
            else:
                curr = first.copy_format_to(f'{first.name}_{k}')
                self.add_signal(curr)
                self.set_next_cycle(curr, hist[k-1])
                hist.append(curr)

        return hist

    def compile_model(self, gen: CodeGenerator):
        # start module
        ios = [signal for signal in self.signals.values() if
               isinstance(signal, (AnalogInput, AnalogOutput, DigitalInput, DigitalOutput))]
        gen.start_module(name=self.name, ios=ios)

        # create internal variables
        internals = [signal for signal in self.signals.values() if
                     not isinstance(signal, (AnalogInput, AnalogOutput, DigitalInput, DigitalOutput))]
        if len(internals) > 0:
            gen.make_section('Declaring internal variables.')
        for signal in internals:
            gen.make_signal(signal)

        # update values of variables for the next cycle
        for assignment in self.assignments:
            # label this section of the code for debugging purposes
            gen.make_section(f'Update signal: {assignment.signal.name}')

            # implement the update expression
            update_signal = gen.compile_expr(assignment.expr)

            if assignment.assignment_type == AssignmentType.THIS_CYCLE:
                gen.make_assign(update_signal, assignment.signal)
            elif assignment.assignment_type == AssignmentType.NEXT_CYCLE:
                gen.make_mem(update_signal, assignment.signal)
            else:
                raise Exception('Invalid assignment type.')

        # add probe signals
        for signal in self.probes:
            gen.make_probe(signal)

        # end module
        gen.end_module()