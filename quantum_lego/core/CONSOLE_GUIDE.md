# Console Output Guide

This guide documents the Rich-based console output system in quantum-lego.

## Overview

Quantum-lego uses the [Rich](https://github.com/Textualize/rich) library for beautiful, colorful terminal output. The console module (`quantum_lego/core/console.py`) provides a centralized interface for all terminal output with:

- **Professional appearance**: Panels, tables, and formatted text
- **Color-coded information**: Status messages, energies, and structure info
- **Automatic fallback**: Works in CI/CD and non-TTY environments
- **Consistent styling**: Unified theme across all modules

## Quick Start

```python
from quantum_lego.core.console import (
    console,
    print_calculation_header,
    print_energy,
    print_status,
    print_warning,
)

# Print a calculation header
print_calculation_header(12345, "VASP Relaxation")

# Print energy with formatting
print_energy(-42.123456)  # Output: Energy: -42.123456 eV (in magenta)

# Print color-coded status
print_status("finished")  # Green color
print_status("running")   # Yellow color
print_status("failed")    # Red color

# Print warning message
print_warning("Files not found in retrieved folder")
```

## Color Theme

The quantum-lego theme defines semantic color mappings:

| Style | Color | Usage |
|-------|-------|-------|
| `info` | Cyan | Informational text |
| `warning` | Yellow | Warning messages |
| `error` | Bold Red | Error messages |
| `success` | Bold Green | Success messages |
| `pk` | Cyan | AiiDA process PKs |
| `energy` | Magenta | Energy values |
| `status.finished` | Green | Finished calculations |
| `status.running` | Yellow | Running calculations |
| `status.failed` | Red | Failed calculations |
| `header` | Bold Cyan | Section headers |
| `value` | White | Generic values |
| `dim` | Dim White | Secondary information |

## Available Functions

### Headers and Status

```python
print_calculation_header(pk: int, calculation_type: str)
# Print a formatted calculation header with panel border
# Example: print_calculation_header(12345, "VASP Relaxation")

print_stage_header(index: int, stage_name: str, brick_type: str = None)
# Print a formatted stage header for sequential workflows
# Example: print_stage_header(1, "relax", "vasp")

print_status(status: str, indent: int = 2)
# Print color-coded status with automatic style selection
# Example: print_status("finished")
```

### Values and Fields

```python
print_energy(energy: float, label: str = "Energy", indent: int = 2)
# Print formatted energy value
# Example: print_energy(-123.456789, "Total Energy")

print_structure_info(formula: str, n_atoms: int = None, pk: int = None, indent: int = 2)
# Print formatted structure information
# Example: print_structure_info("Si2O4", n_atoms=12, pk=67890)

print_field(label: str, value: str, indent: int = 2, value_style: str = "value")
# Print a generic field with label and value
# Example: print_field("Max force", "0.0123 eV/Å", value_style="energy")
```

### Messages

```python
print_warning(message: str, indent: int = 0)
# Print warning message with ⚠ emoji
# Example: print_warning("Files not found")

print_error(message: str, indent: int = 0)
# Print error message with ✖ emoji
# Example: print_error("Calculation failed")

print_success(message: str, indent: int = 0)
# Print success message with ✓ emoji
# Example: print_success("Calculation completed")
```

### Tables

```python
create_results_table(title: str = None, show_header: bool = True) -> Table
# Create a Rich Table with standard quantum-lego styling
# Returns: Rich Table object ready for adding rows

print_dict_as_table(data: dict, title: str = None, 
                    key_header: str = "Property", value_header: str = "Value")
# Print a dictionary as a formatted table
# Example: print_dict_as_table({"Energy": "-123.45 eV", "Status": "finished"})
```

**Table Example:**

```python
from quantum_lego.core.console import console, create_results_table

table = create_results_table(title="Convergence Results")
table.add_column("ENCUT (eV)", justify="right", style="cyan")
table.add_column("Energy (eV)", justify="right", style="magenta")
table.add_column("Converged", style="green")

table.add_row("400", "-42.123456", "No")
table.add_row("520", "-42.125923", "Yes")

console.print(table)
```

### Separators and Sections

```python
print_separator(char: str = "─", length: int = 70, style: str = "dim")
# Print a separator line
# Example: print_separator()

print_section_header(title: str, char: str = "=", style: str = "header")
# Print a section header with decorative lines
# Example: print_section_header("Results Summary")
```

## Direct Console Access

For advanced use cases, use the `console` object directly:

```python
from quantum_lego.core.console import console

# Print with Rich markup
console.print("[bold cyan]Custom message[/bold cyan]")

# Print with specific style
console.print("Status: finished", style="status.finished")

# Print panels
from rich.panel import Panel
console.print(Panel("Important message", border_style="red"))
```

## Rich Markup Reference

Rich uses markup tags for inline styling:

```python
console.print("[bold]Bold text[/bold]")
console.print("[italic]Italic text[/italic]")
console.print("[cyan]Cyan text[/cyan]")
console.print("[bold red]Bold red text[/bold red]")
console.print("[dim]Dimmed text[/dim]")

# Combine styles
console.print("[bold cyan]Bold cyan text[/bold cyan]")

# Use theme styles
console.print("[energy]-42.123456[/energy] eV")
console.print("[pk]12345[/pk]")
```

## Non-TTY Environments

Rich automatically detects terminal capabilities:

- **TTY (terminal)**: Full color and formatting
- **Non-TTY (files, pipes)**: Plain text without ANSI codes
- **CI/CD**: Automatic fallback to plain text

No special handling required! Rich takes care of it.

## Best Practices

### ✅ Do

- Use semantic helper functions (`print_energy`, `print_status`, etc.)
- Use the theme's semantic styles (`[energy]`, `[pk]`, etc.)
- Let Rich handle terminal width automatically
- Use tables for tabular data
- Use consistent indentation (2 or 4 spaces)

### ❌ Don't

- Don't use basic `print()` for user-facing output (use `console.print()`)
- Don't hardcode ANSI color codes
- Don't hardcode terminal width values
- Don't create multiple Console instances (use the singleton)
- Don't mix old `print()` with new Rich output in the same function

## Migration Guide

### From basic print() to Rich

**Before:**
```python
print(f"Energy: {energy:.6f} eV")
print(f"Status: {status}")
```

**After:**
```python
from quantum_lego.core.console import print_energy, print_status

print_energy(energy)
print_status(status)
```

### From manual tables to Rich Tables

**Before:**
```python
print(f"{'ENCUT':>8s}  {'Energy':>12s}")
print(f"{'─' * 8}  {'─' * 12}")
print(f"{encut:8d}  {energy:12.6f}")
```

**After:**
```python
from quantum_lego.core.console import console, create_results_table

table = create_results_table()
table.add_column("ENCUT", justify="right")
table.add_column("Energy", justify="right")
table.add_row(str(encut), f"{energy:.6f}")
console.print(table)
```

## Demonstration

Run the demonstration script to see all features in action:

```bash
python examples/10_utilities/demo_rich_console.py
```

This script shows:
- Calculation headers and status messages
- Energy and structure formatting
- Sequential workflow output
- Warning/error/success messages
- Tables for convergence data
- Non-interactive examples (no AiiDA required)

## Testing

The console module has comprehensive tier1 tests (no AiiDA required):

```bash
pytest tests/test_console.py -m tier1 -v
```

All 18 tests verify:
- Module imports without errors
- Theme configuration
- Console singleton initialization
- Output formatting (via captured output)
- Non-TTY fallback behavior

## Further Reading

- [Rich Documentation](https://rich.readthedocs.io/)
- [Rich GitHub](https://github.com/Textualize/rich)
- [Rich Gallery](https://github.com/Textualize/rich/tree/master/examples)

---

**Last Updated:** 2026-02-09  
**Module:** `quantum_lego/core/console.py`  
**Tests:** `tests/test_console.py`
