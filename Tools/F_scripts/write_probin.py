#!/usr/bin/env python

"""This routine parses plain-text parameter files that list runtime
parameters for use in our codes.  The general format of a parameter
is:

max_step                            integer            1
small_dt                            real               1.d-10
xlo_boundary_type                   character          ""
octant                              logical            .false.

This specifies the runtime parameter name, datatype, and default
value.

An optional 4th column can be used to indicate the priority -- if,
when parsing the collection of parameter files, a duplicate of an
existing parameter is encountered, the value from the one with
the highest priority (largest integer) is retained.

This script takes a template file and replaces keywords in it
(delimited by @@...@@) with the Fortran code required to
initialize the parameters, setup a namelist, and allow for
commandline overriding of their defaults.

"""

from __future__ import print_function

import os
import sys
import argparse

HEADER = """
! DO NOT EDIT THIS FILE!!!
!
! This file is automatically generated by write_probin.py at
! compile-time.
!
! To add a runtime parameter, do so by editting the appropriate _parameters
! file.

"""

CXX_F_HEADER = """
#ifndef _external_parameters_F_H_
#define _external_parameters_F_H_
#include <AMReX.H>
#include <AMReX_BLFort.H>

#ifdef __cplusplus
#include <AMReX.H>
extern "C"
{
#endif
"""

CXX_F_FOOTER = """
#ifdef __cplusplus
}
#endif

#endif
"""

CXX_HEADER = """
#ifndef _external_parameters_H_
#define _external_parameters_H_
#include <AMReX_BLFort.H>

"""

CXX_FOOTER = """
#endif
"""

class Parameter():
    # the simple container to hold the runtime parameters
    def __init__(self):
        self.var = ""
        self.dtype = ""
        self.value = ""
        self.priority = 0

    def get_f90_decl(self):
        """ get the Fortran 90 declaration """
        if self.dtype == "real":
            return "real (kind=rt)"
        elif self.dtype == "character":
            return "character (len=256)"

        return self.dtype

    def get_cxx_decl(self):
        """ get the Fortran 90 declaration """
        if self.dtype == "real":
            return "amrex::Real"
        elif self.dtype == "character":
            return None

        return "int"

    def __lt__(self, other):
        return self.priority < other.priority


def get_next_line(fin):
    # return the next, non-blank line, with comments stripped
    line = fin.readline()

    pos = str.find(line, "#")

    while (pos == 0 or str.strip(line) == "") and line:
        line = fin.readline()
        pos = str.find(line, "#")

    return line[:pos]


def parse_param_file(params_list, param_file):
    """read all the parameters in a given parameter file and add valid
    parameters to the params list.
    """

    err = 0

    try:
        f = open(param_file, "r")
    except IOError:
        sys.exit("write_probin.py: ERROR: file {} does not exist".format(param_file))
    else:
        print("write_probin.py: working on parameter file {}...".format(param_file))

    line = get_next_line(f)

    while line and not err:

        fields = line.split()

        if len(fields) < 3:
            print("write_probin.py: ERROR: missing one or more fields in parameter definition.")
            err = 1
            continue

        current_param = Parameter()

        current_param.var = fields[0]
        current_param.dtype = fields[1]
        current_param.value = fields[2]

        try:
            current_param.priority = int(fields[3])
        except:
            pass

        skip = 0

        # check to see if this parameter is defined in the current list
        # if so, keep the one with the highest priority
        p_names = [p.var for p in params_list]
        try:
            idx = p_names.index(current_param.var)
        except:
            idx = -1
        else:
            if params_list[idx] < current_param:
                params_list.pop(idx)
            else:
                skip = 1

        if not err == 1 and not skip == 1:
            params_list.append(current_param)

        line = get_next_line(f)

    return err


def abort(outfile):
    """ abort exits when there is an error.  A dummy stub file is written
    out, which will cause a compilation failure """

    fout = open(outfile, "w")
    fout.write("There was an error parsing the parameter files")
    fout.close()
    sys.exit(1)


def write_probin(probin_template, param_files,
                 namelist_name, out_file, cxx_prefix, managed=False):

    """ write_probin will read through the list of parameter files and
    output the new out_file """

    params = []

    print(" ")
    print("write_probin.py: creating {}".format(out_file))

    # read the parameters defined in the parameter files

    for f in param_files:
        err = parse_param_file(params, f)
        if err:
            abort(out_file)

    # open up the template
    try:
        ftemplate = open(probin_template, "r")
    except IOError:
        sys.exit("write_probin.py: ERROR: file {} does not exist".format(probin_template))

    template_lines = ftemplate.readlines()

    ftemplate.close()

    # output the template, inserting the parameter info in between the @@...@@
    fout = open(out_file, "w")

    fout.write(HEADER)

    for line in template_lines:

        index = line.find("@@")

        if index >= 0:
            index2 = line.rfind("@@")

            keyword = line[index+len("@@"):index2]
            indent = index*" "

            if keyword in ["declarationsA", "declarations"]:

                # declaraction statements
                for p in params:

                    dtype = p.dtype

                    if dtype == "character":
                        if managed:
                            fout.write("{}{}, public :: {}\n".format(
                                indent, p.get_f90_decl(), p.var, p.value))
                        else:
                            fout.write("{}{}, save, public :: {} = {}\n".format(
                                indent, p.get_f90_decl(), p.var, p.value))
                        fout.write("{}!$acc declare create({})\n".format(indent, p.var))

                    else:
                        if managed:
                            fout.write("{}{}, allocatable, public :: {}\n".format(
                                indent, p.get_f90_decl(), p.var, p.value))
                        else:
                            fout.write("{}{}, save, public :: {} = {}\n".format(
                                indent, p.get_f90_decl(), p.var, p.value))
                        fout.write("{}!$acc declare create({})\n".format(indent, p.var))

                if not params:
                    # we always make sure there is atleast one variable
                    fout.write("{}integer, save, public :: a_dummy_var = 0\n".format(indent))

            elif keyword in ["cudaattributesA", "cudaattributes"]:
                if managed:
                    for p in params:
                        if p.dtype != "character":
                            fout.write("{}attributes(managed) :: {}\n".format(indent, p.var))

            elif keyword == "allocations":
                if managed:
                    for p in params:
                        if p.dtype != "character":
                            fout.write("{}allocate({})\n".format(indent, p.var))

            elif keyword == "initialize":
                if managed:
                    for p in params:
                        fout.write("{}{} = {}\n".format(indent, p.var, p.value))

            elif keyword == "deallocations":
                if managed:
                    for p in params:
                        if p.dtype != "character":
                            fout.write("{}deallocate({})\n".format(indent, p.var))

            elif keyword == "namelist":
                for p in params:
                    fout.write("{}namelist /{}/ {}\n".format(
                        indent, namelist_name, p.var))

                if not params:
                    fout.write("{}namelist /{}/ a_dummy_var\n".format(
                        indent, namelist_name))

            elif keyword == "defaults":

                for p in params:
                    fout.write("{}{} = {}\n".format(
                        indent, p.var, p.value))

            elif keyword == "commandline":

                for p in params:

                    fout.write("{}case (\'--{}\')\n".format(indent, p.var))
                    fout.write("{}   farg = farg + 1\n".format(indent))

                    if p.dtype == "character":
                        fout.write("{}   call get_command_argument(farg, value = {})\n".format(
                            indent, p.var))

                    else:
                        fout.write("{}   call get_command_argument(farg, value = fname)\n".format(indent))
                        fout.write("{}   read(fname, *) {}\n".format(indent, p.var))

            elif keyword == "printing":

                fout.write("100 format (1x, a3, 2x, a32, 1x, \"=\", 1x, a)\n")
                fout.write("101 format (1x, a3, 2x, a32, 1x, \"=\", 1x, i10)\n")
                fout.write("102 format (1x, a3, 2x, a32, 1x, \"=\", 1x, g20.10)\n")
                fout.write("103 format (1x, a3, 2x, a32, 1x, \"=\", 1x, l)\n")

                for p in params:

                    dtype = p.dtype

                    if dtype == "logical":
                        ltest = "\n{}ltest = {} .eqv. {}\n".format(indent, p.var, p.value)
                    else:
                        ltest = "\n{}ltest = {} == {}\n".format(indent, p.var, p.value)

                    fout.write(ltest)

                    cmd = "merge(\"   \", \"[*]\", ltest)"

                    if dtype == "real":
                        fout.write("{}write (unit,102) {}, &\n \"{}\", {}\n".format(
                            indent, cmd, p.var, p.var))

                    elif dtype == "character":
                        fout.write("{}write (unit,100) {}, &\n \"{}\", trim({})\n".format(
                            indent, cmd, p.var, p.var))

                    elif dtype == "integer":
                        fout.write("{}write (unit,101) {}, &\n \"{}\", {}\n".format(
                            indent, cmd, p.var, p.var))

                    elif dtype == "logical":
                        fout.write("{}write (unit,103) {}, &\n \"{}\", {}\n".format(
                            indent, cmd, p.var, p.var))

                    else:
                        print("write_probin.py: invalid datatype for variable {}".format(p.var))


            elif keyword == "acc":

                fout.write(indent + "!$acc update &\n")
                fout.write(indent + "!$acc device(")

                for n, p in enumerate(params):
                    fout.write("{}".format(p.var))

                    if n == len(params)-1:
                        fout.write(")\n")
                    else:
                        if n % 3 == 2:
                            fout.write(") &\n" + indent + "!$acc device(")
                        else:
                            fout.write(", ")

            elif keyword == "cxx_gets":
                # this writes out the Fortran functions that can be
                # called from C++ to get the value of the parameters

                for p in params:
                    if p.dtype == "character":
                        fout.write("{}subroutine get_f90_{}_len(slen) bind(C, name=\"get_f90_{}_len\")\n".format(
                            indent, p.var, p.var))
                        fout.write("{}   integer, intent(inout) :: slen\n".format(indent))
                        fout.write("{}   slen = len(trim({}))\n".format(indent, p.var))
                        fout.write("{}end subroutine get_f90_{}_len\n\n".format(indent, p.var))

                        fout.write("{}subroutine get_f90_{}({}_in) bind(C, name=\"get_f90_{}\")\n".format(
                            indent, p.var, p.var, p.var))
                        fout.write("{}   character(kind=c_char) :: {}_in(*)\n".format(
                            indent, p.var))
                        fout.write("{}   integer :: n\n".format(indent))
                        fout.write("{}   do n = 1, len(trim({}))\n".format(indent, p.var))
                        fout.write("{}      {}_in(n:n) = {}(n:n)\n".format(indent, p.var, p.var))
                        fout.write("{}   end do\n".format(indent))
                        fout.write("{}   {}_in(len(trim({}))+1) = char(0)\n".format(indent, p.var, p.var))
                        fout.write("{}end subroutine get_f90_{}\n\n".format(indent, p.var))

                    elif p.dtype == "logical":
                        # F90 logicals are integers in C++
                        fout.write("{}subroutine get_f90_{}({}_in) bind(C, name=\"get_f90_{}\")\n".format(
                            indent, p.var, p.var, p.var))
                        fout.write("{}   integer, intent(inout) :: {}_in\n".format(
                            indent, p.var))
                        fout.write("{}   {}_in = 0\n".format(indent, p.var))
                        fout.write("{}   if ({}) then\n".format(indent, p.var))
                        fout.write("{}      {}_in = 1\n".format(indent, p.var))
                        fout.write("{}   endif\n".format(indent))
                        fout.write("{}end subroutine get_f90_{}\n\n".format(
                            indent, p.var))

                    else:
                        fout.write("{}subroutine get_f90_{}({}_in) bind(C, name=\"get_f90_{}\")\n".format(
                            indent, p.var, p.var, p.var))
                        fout.write("{}   {}, intent(inout) :: {}_in\n".format(
                            indent, p.get_f90_decl(), p.var))
                        fout.write("{}   {}_in = {}\n".format(
                            indent, p.var, p.var))
                        fout.write("{}end subroutine get_f90_{}\n\n".format(
                            indent, p.var))


        else:
            fout.write(line)

    print(" ")
    fout.close()

    # now handle the C++ -- we need to write a header and a .cpp file
    # for the parameters + a _F.H file for the Fortran communication

    # first the _F.H file
    ofile = "{}_parameters_F.H".format(cxx_prefix)
    with open(ofile, "w") as fout:
        fout.write(CXX_F_HEADER)

        for p in params:
            if p.dtype == "character":
                fout.write("  void get_f90_{}(char* {});\n\n".format(
                    p.var, p.var))
                fout.write("  void get_f90_{}_len(int& slen);\n\n".format(p.var))

            else:
                fout.write("  void get_f90_{}({}* {});\n\n".format(
                    p.var, p.get_cxx_decl(), p.var))

        fout.write(CXX_F_FOOTER)

    # now the main C++ header with the global data
    ofile = "{}_parameters.H".format(cxx_prefix)
    with open(ofile, "w") as fout:
        fout.write(CXX_HEADER)

        fout.write("  void init_{}_parameters();\n\n".format(os.path.basename(cxx_prefix)))

        for p in params:
            if p.dtype == "character":
                fout.write("  extern std::string {};\n\n".format(p.var))
            else:
                fout.write("  extern AMREX_GPU_MANAGED {} {};\n\n".format(p.get_cxx_decl(), p.var))

        fout.write(CXX_FOOTER)

    # finally the C++ initialization routines
    ofile = "{}_parameters.cpp".format(cxx_prefix)
    with open(ofile, "w") as fout:
        fout.write("#include <{}_parameters.H>\n".format(os.path.basename(cxx_prefix)))
        fout.write("#include <{}_parameters_F.H>\n\n".format(os.path.basename(cxx_prefix)))

        for p in params:
            if p.dtype == "character":
                fout.write("  std::string {};\n\n".format(p.var))
            else:
                fout.write("  AMREX_GPU_MANAGED {} {};\n\n".format(p.get_cxx_decl(), p.var))

        fout.write("\n")
        fout.write("  void init_{}_parameters() {{\n".format(os.path.basename(cxx_prefix)))
        fout.write("    int slen = 0;\n\n")

        for p in params:
            if p.dtype == "character":
                fout.write("    get_f90_{}_len(slen);\n".format(p.var))
                fout.write("    char _{}[slen+1];\n".format(p.var))
                fout.write("    get_f90_{}(_{});\n".format(p.var, p.var))
                fout.write("    {} = std::string(_{});\n\n".format(p.var, p.var))
            else:
                fout.write("    get_f90_{}(&{});\n\n".format(p.var, p.var))

        fout.write("  }\n")

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('-t', type=str, help='probin_template')
    parser.add_argument('-o', type=str, help='out_file')
    parser.add_argument('-n', type=str, help='namelist_name')
    parser.add_argument('--pa', type=str, help='parameter files')
    parser.add_argument('--cxx_prefix', type=str, default="extern",
                        help="a name to use in the C++ file names")
    parser.add_argument('--managed', action='store_true',
                        help='If supplied, use CUDA managed memory for probin variables.')

    args = parser.parse_args()

    probin_template = args.t
    out_file = args.o
    namelist_name = args.n
    param_files_str = args.pa

    if (probin_template == "" or out_file == "" or namelist_name == ""):
        sys.exit("write_probin.py: ERROR: invalid calling sequence")

    param_files = param_files_str.split()

    write_probin(probin_template, param_files,
                 namelist_name, out_file, args.cxx_prefix, managed=args.managed)

if __name__ == "__main__":
    main()
