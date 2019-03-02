from typing import List
from numbers import Number

from msdsl.expr.signals import Signal
from msdsl.expr.expr import ModelExpr
from msdsl.util import Namer

class CodeGenerator:
    def __init__(self, tab_string: str=None, line_ending: str=None, namer: Namer=None):
        # save settings
        self.tab_string = tab_string if tab_string is not None else '    '
        self.line_ending = line_ending if line_ending is not None else '\n'
        self.namer = namer if namer is not None else Namer()

        # initialize variables
        self.tab_level = 0
        self.text = ''

    # concrete functions

    def indent(self):
        self.tab_level += 1

    def dedent(self):
        self.tab_level -= 1
        assert self.tab_level >= 0

    def write(self, string=''):
        self.text += string

    def writeln(self, line=''):
        self.write(self.tab_level * self.tab_string + line + self.line_ending)

    def write_to_file(self, filename):
        with open(filename, 'w') as f:
            f.write(self.text)

    ###############################
    # abstract methods
    ###############################

    def make_section(self, label):
        raise NotImplementedError

    def make_signal(self, s: Signal):
        raise NotImplementedError

    def make_probe(self, s: Signal):
        raise NotImplementedError

    def make_assign(self, input_: Signal, output: Signal):
        raise NotImplementedError

    def make_mem(self, next: Signal, curr: Signal, init: Number=0):
        raise NotImplementedError

    def expr_to_signal(self, expr: ModelExpr):
        raise NotImplementedError

    def start_module(self, name: str, ios: List[Signal]):
        raise NotImplementedError

    def end_module(self):
        raise NotImplementedError

def main():
    gen = CodeGenerator()
    gen.writeln('1. Outer')
    gen.indent()
    gen.writeln('1.1 Inner')
    gen.writeln('1.2 Inner')
    gen.dedent()
    gen.writeln('2. Outer')
    print(gen.text)

if __name__ == '__main__':
    main()