"""Console output utilities using Rich for beautiful terminal formatting.

This module provides a centralized interface for all terminal output in quantum-lego,
using the Rich library for professional, colorful console output with automatic
terminal capability detection and fallback for non-TTY environments.

Example:
    >>> from quantum_lego.core.console import console, print_calculation_header
    >>> print_calculation_header(12345, "VASP Relaxation")
    >>> console.print("[bold green]✓ Success:[/bold green] Calculation completed")
"""

from rich.console import Console
from rich.theme import Theme
from rich.table import Table
from rich.panel import Panel


# Custom theme for quantum-lego with semantic color naming
QUANTUM_LEGO_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "pk": "cyan",
    "energy": "magenta",
    "status.finished": "green",
    "status.running": "yellow",
    "status.failed": "red",
    "header": "bold cyan",
    "value": "white",
    "dim": "dim white",
})

# Singleton console instance for consistent output across the package
console = Console(theme=QUANTUM_LEGO_THEME)


def print_calculation_header(pk: int, calculation_type: str) -> None:
    """Print a formatted calculation header with panel border.

    Args:
        pk: Process PK (AiiDA node identifier)
        calculation_type: Type of calculation (e.g., "VASP Relaxation", "DOS")

    Example:
        >>> print_calculation_header(12345, "VASP Relaxation")
    """
    console.print(Panel(
        f"[header]{calculation_type}[/header] - PK [pk]{pk}[/pk]",
        border_style="blue"
    ))


def print_stage_header(index: int, stage_name: str, brick_type: str = None) -> None:
    """Print a formatted stage header for sequential workflows.

    Args:
        index: Stage index number
        stage_name: Name of the stage
        brick_type: Optional brick type (e.g., "vasp", "dos")

    Example:
        >>> print_stage_header(1, "relax", "vasp")
    """
    if brick_type:
        console.print(f"\n[header]Stage {index}:[/header] {stage_name} ({brick_type})")
    else:
        console.print(f"\n[header]Stage {index}:[/header] {stage_name}")


def print_energy(energy: float, label: str = "Energy", indent: int = 2) -> None:
    """Print formatted energy value with consistent styling.

    Args:
        energy: Energy value in eV
        label: Label for the energy (default: "Energy")
        indent: Number of spaces for indentation (default: 2)

    Example:
        >>> print_energy(-123.456789, "Total Energy")
          Total Energy: -123.456789 eV
    """
    spaces = " " * indent
    console.print(f"{spaces}[bold]{label}:[/bold] [energy]{energy:.6f}[/energy] eV")


def print_status(status: str, indent: int = 2) -> None:
    """Print color-coded status with automatic style selection.

    Args:
        status: Status string (e.g., "finished", "running", "failed")
        indent: Number of spaces for indentation (default: 2)

    Example:
        >>> print_status("finished")
          Status: finished  # (in green)
    """
    spaces = " " * indent
    # Map status to theme style
    status_lower = status.lower()
    if status_lower in ["finished", "completed"]:
        style = "status.finished"
    elif status_lower in ["running", "waiting", "queued"]:
        style = "status.running"
    elif status_lower in ["failed", "error", "killed"]:
        style = "status.failed"
    else:
        style = "value"

    console.print(f"{spaces}[bold]Status:[/bold] [{style}]{status}[/{style}]")


def print_structure_info(formula: str, n_atoms: int = None, pk: int = None, indent: int = 2) -> None:
    """Print formatted structure information.

    Args:
        formula: Chemical formula string
        n_atoms: Number of atoms (optional)
        pk: Structure PK (optional)
        indent: Number of spaces for indentation (default: 2)

    Example:
        >>> print_structure_info("SiO2", n_atoms=12, pk=67890)
          Structure: SiO2 (12 atoms, PK: 67890)
    """
    spaces = " " * indent
    parts = [formula]
    if n_atoms is not None or pk is not None:
        details = []
        if n_atoms is not None:
            details.append(f"{n_atoms} atoms")
        if pk is not None:
            details.append(f"PK: {pk}")
        parts.append(f"[dim]({', '.join(details)})[/dim]")

    console.print(f"{spaces}[bold]Structure:[/bold] {' '.join(parts)}")


def print_warning(message: str, indent: int = 0) -> None:
    """Print a warning message with warning emoji and styling.

    Args:
        message: Warning message text
        indent: Number of spaces for indentation (default: 0)

    Example:
        >>> print_warning("Files not found in retrieved")
        ⚠ Warning: Files not found in retrieved
    """
    spaces = " " * indent
    console.print(f"{spaces}[warning]⚠ Warning:[/warning] {message}")


def print_error(message: str, indent: int = 0) -> None:
    """Print an error message with error emoji and styling.

    Args:
        message: Error message text
        indent: Number of spaces for indentation (default: 0)

    Example:
        >>> print_error("Calculation failed to converge")
        ✖ Error: Calculation failed to converge
    """
    spaces = " " * indent
    console.print(f"{spaces}[error]✖ Error:[/error] {message}")


def print_success(message: str, indent: int = 0) -> None:
    """Print a success message with checkmark emoji and styling.

    Args:
        message: Success message text
        indent: Number of spaces for indentation (default: 0)

    Example:
        >>> print_success("Calculation completed successfully")
        ✓ Success: Calculation completed successfully
    """
    spaces = " " * indent
    console.print(f"{spaces}[success]✓ Success:[/success] {message}")


def print_field(label: str, value: str, indent: int = 2, value_style: str = "value") -> None:
    """Print a generic field with label and value.

    Args:
        label: Field label
        value: Field value
        indent: Number of spaces for indentation (default: 2)
        value_style: Rich style for the value (default: "value")

    Example:
        >>> print_field("Max force", "0.0123 eV/Å", value_style="energy")
          Max force: 0.0123 eV/Å
    """
    spaces = " " * indent
    console.print(f"{spaces}[bold]{label}:[/bold] [{value_style}]{value}[/{value_style}]")


def create_results_table(title: str = None, show_header: bool = True) -> Table:
    """Create a Rich Table with standard quantum-lego styling.

    Args:
        title: Optional table title
        show_header: Whether to show table header (default: True)

    Returns:
        Rich Table object ready for adding rows

    Example:
        >>> table = create_results_table("Convergence Results")
        >>> table.add_column("Parameter", style="cyan")
        >>> table.add_column("Value", style="magenta")
        >>> table.add_row("ENCUT", "520 eV")
        >>> console.print(table)
    """
    return Table(
        title=title,
        show_header=show_header,
        header_style="header",
        border_style="blue"
    )


def print_separator(char: str = "─", length: int = 70, style: str = "dim") -> None:
    """Print a separator line.

    Args:
        char: Character to use for separator (default: "─")
        length: Length of separator (default: 70)
        style: Rich style for the separator (default: "dim")

    Example:
        >>> print_separator()
        ──────────────────────────────────────────────────────────────────
    """
    console.print(f"[{style}]{char * length}[/{style}]")


def print_section_header(title: str, char: str = "=", style: str = "header") -> None:
    """Print a section header with decorative lines.

    Args:
        title: Section title text
        char: Character to use for decorative lines (default: "=")
        style: Rich style for the header (default: "header")

    Example:
        >>> print_section_header("Results Summary")
        ======================================================================
        Results Summary
        ======================================================================
    """
    line = char * 70
    console.print(f"\n[{style}]{line}[/{style}]")
    console.print(f"[{style}]{title}[/{style}]")
    console.print(f"[{style}]{line}[/{style}]")


def print_dict_as_table(data: dict, title: str = None, key_header: str = "Property",
                        value_header: str = "Value") -> None:
    """Print a dictionary as a formatted table.

    Args:
        data: Dictionary to display
        title: Optional table title
        key_header: Header for keys column (default: "Property")
        value_header: Header for values column (default: "Value")

    Example:
        >>> print_dict_as_table({"Energy": "-123.45 eV", "Status": "finished"},
        ...                     title="Calculation Results")
    """
    table = create_results_table(title=title, show_header=True)
    table.add_column(key_header, style="bold")
    table.add_column(value_header, style="value")

    for key, value in data.items():
        table.add_row(str(key), str(value))

    console.print(table)
