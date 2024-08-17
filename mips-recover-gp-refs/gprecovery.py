#!/usr/bin/env python3
"""Locate missing import references resolved via offsets from $gp and annotate them in the bndb"""

import argparse
import pathlib
import sys

from binaryninja import load
from binaryninja.enums import LogLevel, SymbolType
from binaryninja.log import log_to_file, log_info
from binaryninja.types import CoreSymbol


def save_bndb(fname, view, name):
    """Save a bndb."""
    return view.create_database(f'{fname}_{name}.bndb')


def process_file(bin_path):
    """Locate lw instructions using an immediate offset to $gp, annotate them."""
    view = load(bin_path.name)
    view.update_analysis_and_wait()

    # save off the default analysis before we muck with the view
    save_bndb(bin_path.name, view, 'default_analysis')

    # find canonical $gp as `_gp`
    gp_syms = view.get_symbols_by_name('_gp')

    gp_sym = None
    for sym in gp_syms:
        if sym.type == SymbolType.DataSymbol:
            gp_sym = sym

    if not gp_sym:
        log_info('Unable to find canonical $gp', 'gprecovery')
        return 1

    log_info(f'Found canonical $gp at: {hex(gp_sym.address)}', 'gprecovery')
    log_info('Candidates for gp-based offset reference recovery:', 'gprecovery')

    for func in view.functions:
        for block in func.basic_blocks:
            for idx, inst in enumerate(block):
                # lw    DestGpr, Imm16(Gpr)
                # lw    $t9, -0x7dd8($gp)

                # min size of inst list
                if len(inst[0]) < 7:
                    continue

                # need load word instruction, which will always be first
                if inst[0][0].text != 'lw':
                    continue

                # need $gp, which will always be the Src Gpr
                if inst[0][7].text != '$gp':
                    continue

                # need an immediate value as an offset into $gp
                try:
                    imm = int(inst[0][5].text, 16)
                except ValueError:
                    continue

                # it should be a reference to the got
                got_sym = view.get_symbol_at(imm + gp_sym.address)

                if not isinstance(got_sym, CoreSymbol):
                    continue

                # need to only care about imports
                if got_sym.type != SymbolType.ImportAddressSymbol:
                    continue

                addr = block.start + (4 * idx)

                # log the candidates we touched
                log_info(f'{hex(addr)} {''.join(str(mnem) for mnem in inst[0])}', 'gprecovery')

                func.set_comment_at(addr, got_sym.name)
                view.add_user_data_ref(addr, got_sym.address)

    save_bndb(bin_path.name, view, 'after_analysis')
    return 0


def main():
    """main."""
    parser = argparse.ArgumentParser(
        description='Annotate a bndb, via a user data reference and comment, missing import cross-references for MIPS32'
    )

    parser.add_argument(
        'binary',
        help='Path to binary',
        type=pathlib.Path,
    )

    args = parser.parse_args()

    log_to_file(LogLevel.InfoLog, 'binja.log', append=True)
    log_info(f"Processing '{args.binary}'", 'gprecovery')

    try:
        process_file(args.binary)
    except Exception as excep:
        log_info(f'Uncaught exception: {excep}', 'gprecovery')
        raise

    return 0


if __name__ == '__main__':
    sys.exit(main())
