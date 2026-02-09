#!/usr/bin/env python3
"""
Demonstration script for Rich console output in quantum-lego.

This script shows examples of the new Rich-based console output without requiring
AiiDA or any calculations. It demonstrates the visual improvements to terminal output.
"""

import sys
import os

# Add quantum_lego/core to path to import console directly
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'quantum_lego', 'core'))

from console import (
    console,
    print_calculation_header,
    print_stage_header,
    print_energy,
    print_status,
    print_structure_info,
    print_field,
    print_warning,
    print_error,
    print_success,
    print_section_header,
    print_separator,
    create_results_table,
    print_dict_as_table,
)


def demo_calculation_output():
    """Demonstrate calculation results output."""
    print_section_header("Calculation Results Example")
    console.print()

    print_calculation_header(12345, "VASP Relaxation")
    print_status("finished")
    print_energy(-42.123456, "Total Energy")
    print_structure_info("Si2O4", n_atoms=12, pk=67890)
    print_field("Max force", "0.0234 eV/Å")
    print_field("Retrieved files", "OUTCAR, vasprun.xml, CONTCAR")


def demo_dos_results():
    """Demonstrate DOS calculation output."""
    console.print("\n")
    print_section_header("DOS Calculation Example")
    console.print()

    print_calculation_header(54321, "DOS Calculation")
    print_status("finished")
    print_energy(-42.987654, "SCF Energy")
    print_structure_info("SnO2", n_atoms=24, pk=98765)
    print_field("SCF converged", "True")
    print_field("Band gap", "3.6 eV (indirect)", value_style="energy")
    print_field("Fermi level", "-5.234 eV", value_style="energy")


def demo_sequential_workflow():
    """Demonstrate sequential workflow output."""
    console.print("\n")
    print_section_header("Sequential Workflow Example")
    console.print()

    print_calculation_header(11111, "Sequential VASP Calculation")
    print_status("finished")
    console.print(f"  [bold]Stages:[/bold] 3")
    console.print()

    # Stage 1: Relaxation
    print_stage_header(1, "relax", "vasp")
    console.print(f"      [bold]Energy:[/bold] [energy]-42.123456[/energy] eV")
    console.print(f"      [bold]Structure:[/bold] Si2O4 [dim](12 atoms, PK: 22222)[/dim]")
    console.print(f"      [bold]Status:[/bold] finished")
    console.print()

    # Stage 2: SCF
    print_stage_header(2, "scf", "vasp")
    console.print(f"      [bold]Energy:[/bold] [energy]-42.234567[/energy] eV")
    console.print(f"      [bold]Structure:[/bold] Si2O4 [dim](12 atoms, PK: 33333)[/dim]")
    console.print(f"      [bold]Status:[/bold] finished")
    console.print()

    # Stage 3: DOS
    print_stage_header(3, "dos_calc", "dos")
    console.print(f"      [bold]SCF Energy:[/bold] [energy]-42.234567[/energy] eV")
    console.print(f"      [bold]Band gap:[/bold] [energy]3.6[/energy] eV (indirect)")
    console.print(f"      [bold]Fermi level:[/bold] [energy]-5.234[/energy] eV")


def demo_status_messages():
    """Demonstrate different status message types."""
    console.print("\n")
    print_section_header("Status Messages Example")
    console.print()

    console.print("[bold]Finished calculations:[/bold]")
    print_status("finished", indent=2)
    console.print()

    console.print("[bold]Running calculations:[/bold]")
    print_status("running", indent=2)
    console.print()

    console.print("[bold]Failed calculations:[/bold]")
    print_status("failed", indent=2)
    console.print()

    console.print("[bold]Message types:[/bold]")
    print_success("Calculation completed successfully", indent=2)
    print_warning("Files not found in retrieved folder", indent=2)
    print_error("Calculation failed to converge", indent=2)


def demo_table_output():
    """Demonstrate table output."""
    console.print("\n")
    print_section_header("Table Output Example")
    console.print()

    # Convergence table example
    table = create_results_table(title="ENCUT Convergence Results")
    table.add_column("ENCUT (eV)", justify="right", style="cyan")
    table.add_column("Energy (eV)", justify="right", style="magenta")
    table.add_column("Δ Energy (meV)", justify="right", style="yellow")

    table.add_row("400", "-42.123456", "—")
    table.add_row("450", "-42.125123", "1.667")
    table.add_row("500", "-42.125876", "0.753")
    table.add_row("520", "-42.125923", "0.047", style="green")  # Converged

    console.print(table)
    console.print()

    # Dictionary as table example
    print_dict_as_table(
        {
            "Code": "VASP-6.5.1@localwork",
            "K-points": "5x5x1 (Gamma)",
            "ENCUT": "520 eV",
            "ISMEAR": "0",
            "Convergence": "1e-6 eV",
        },
        title="Calculation Parameters",
        key_header="Parameter",
        value_header="Value"
    )


def demo_separator():
    """Demonstrate separator line."""
    console.print("\n")
    print_separator()
    console.print("[bold cyan]End of Demonstration[/bold cyan]")
    print_separator()


def main():
    """Run all demonstrations."""
    console.print("\n[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  Quantum Lego - Rich Console Output Demonstration[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print()
    console.print("[dim]This demonstration shows the new Rich-based console output for quantum-lego.[/dim]")
    console.print("[dim]All output is styled with colors, formatting, and proper visual hierarchy.[/dim]")
    console.print()

    demo_calculation_output()
    demo_dos_results()
    demo_sequential_workflow()
    demo_status_messages()
    demo_table_output()
    demo_separator()

    console.print()
    console.print("[bold green]✓[/bold green] Demonstration completed!")
    console.print()
    console.print("[dim]Note: Colors and formatting automatically adapt to your terminal capabilities.[/dim]")
    console.print("[dim]In non-TTY environments (e.g., CI/CD), output falls back to plain text.[/dim]")
    console.print()


if __name__ == "__main__":
    main()
