#!/usr/bin/env python3
"""Demonstrate Rich-based console output helpers.

API functions: console helpers from quantum_lego.core.console
Difficulty: beginner
Usage:
    python examples/10_utilities/demo_rich_console.py
"""

from quantum_lego.core.console import (
    console,
    create_results_table,
    print_calculation_header,
    print_dict_as_table,
    print_energy,
    print_error,
    print_field,
    print_section_header,
    print_separator,
    print_stage_header,
    print_status,
    print_structure_info,
    print_success,
    print_warning,
)


def demo_calculation_output() -> None:
    print_section_header('Calculation Results Example')
    console.print()

    print_calculation_header(12345, 'VASP Relaxation')
    print_status('finished')
    print_energy(-42.123456, 'Total Energy')
    print_structure_info('Si2O4', n_atoms=12, pk=67890)
    print_field('Max force', '0.0234 eV/A')
    print_field('Retrieved files', 'OUTCAR, vasprun.xml, CONTCAR')


def demo_dos_results() -> None:
    console.print('\n')
    print_section_header('DOS Calculation Example')
    console.print()

    print_calculation_header(54321, 'DOS Calculation')
    print_status('finished')
    print_energy(-42.987654, 'SCF Energy')
    print_structure_info('SnO2', n_atoms=24, pk=98765)
    print_field('SCF converged', 'True')
    print_field('Band gap', '3.6 eV (indirect)', value_style='energy')
    print_field('Fermi level', '-5.234 eV', value_style='energy')


def demo_sequential_workflow() -> None:
    console.print('\n')
    print_section_header('Sequential Workflow Example')
    console.print()

    print_calculation_header(11111, 'Sequential VASP Calculation')
    print_status('finished')
    console.print('  [bold]Stages:[/bold] 3')
    console.print()

    print_stage_header(1, 'relax', 'vasp')
    console.print('      [bold]Energy:[/bold] [energy]-42.123456[/energy] eV')
    console.print('      [bold]Structure:[/bold] Si2O4 [dim](12 atoms, PK: 22222)[/dim]')
    console.print('      [bold]Status:[/bold] finished')
    console.print()

    print_stage_header(2, 'scf', 'vasp')
    console.print('      [bold]Energy:[/bold] [energy]-42.234567[/energy] eV')
    console.print('      [bold]Structure:[/bold] Si2O4 [dim](12 atoms, PK: 33333)[/dim]')
    console.print('      [bold]Status:[/bold] finished')
    console.print()

    print_stage_header(3, 'dos_calc', 'dos')
    console.print('      [bold]SCF Energy:[/bold] [energy]-42.234567[/energy] eV')
    console.print('      [bold]Band gap:[/bold] [energy]3.6[/energy] eV (indirect)')
    console.print('      [bold]Fermi level:[/bold] [energy]-5.234[/energy] eV')


def demo_status_messages() -> None:
    console.print('\n')
    print_section_header('Status Messages Example')
    console.print()

    console.print('[bold]Finished calculations:[/bold]')
    print_status('finished', indent=2)
    console.print()

    console.print('[bold]Running calculations:[/bold]')
    print_status('running', indent=2)
    console.print()

    console.print('[bold]Failed calculations:[/bold]')
    print_status('failed', indent=2)
    console.print()

    console.print('[bold]Message types:[/bold]')
    print_success('Calculation completed successfully', indent=2)
    print_warning('Files not found in retrieved folder', indent=2)
    print_error('Calculation failed to converge', indent=2)


def demo_table_output() -> None:
    console.print('\n')
    print_section_header('Table Output Example')
    console.print()

    table = create_results_table(title='ENCUT Convergence Results')
    table.add_column('ENCUT (eV)', justify='right', style='cyan')
    table.add_column('Energy (eV)', justify='right', style='magenta')
    table.add_column('Delta Energy (meV)', justify='right', style='yellow')

    table.add_row('400', '-42.123456', '-')
    table.add_row('450', '-42.125123', '1.667')
    table.add_row('500', '-42.125876', '0.753')
    table.add_row('520', '-42.125923', '0.047', style='green')

    console.print(table)
    console.print()

    print_dict_as_table(
        {
            'Code': 'VASP-6.5.1@localwork',
            'K-points': '5x5x1 (Gamma)',
            'ENCUT': '520 eV',
            'ISMEAR': '0',
            'Convergence': '1e-6 eV',
        },
        title='Calculation Parameters',
        key_header='Parameter',
        value_header='Value',
    )


def demo_separator() -> None:
    console.print('\n')
    print_separator()
    console.print('[bold cyan]End of Demonstration[/bold cyan]')
    print_separator()


def main() -> None:
    console.print('\n[bold cyan]===============================================================[/bold cyan]')
    console.print('[bold cyan]  Quantum Lego - Rich Console Output Demonstration[/bold cyan]')
    console.print('[bold cyan]===============================================================[/bold cyan]')
    console.print()
    console.print('[dim]Demonstrates Rich formatting helpers without running calculations.[/dim]')
    console.print()

    demo_calculation_output()
    demo_dos_results()
    demo_sequential_workflow()
    demo_status_messages()
    demo_table_output()
    demo_separator()

    console.print()
    console.print('[bold green]Done[/bold green] Demonstration completed.')
    console.print()


if __name__ == '__main__':
    main()
