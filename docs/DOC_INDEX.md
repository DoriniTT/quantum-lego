# Quantum Lego Documentation Index

Welcome to the Quantum Lego documentation! This page helps you navigate the documentation and find what you need.

## 🎯 Start Here

**New to Quantum Lego?** Follow this path:

1. **[QUICK_START.md](QUICK_START.md)** - Get your first calculation running in 5 minutes
2. **[VISUAL_GUIDE.md](VISUAL_GUIDE.md)** - See visual diagrams of common workflows
3. **[DOCUMENTATION.md](DOCUMENTATION.md)** - Deep dive into all features
4. **[AGENTS.md](AGENTS.md)** - Developer and technical reference

---

## 📖 Documentation Files

### [QUICK_START.md](QUICK_START.md) - Beginner's Guide
**Who:** New users, quick reference
**What you'll learn:**
- Basic installation and setup
- Your first VASP calculation
- Common calculation types (relax, DOS, batch)
- Sequential workflows
- Mixed-source DOS stages (`structure_from` and explicit `structure`)
- Essential monitoring commands
- Common pitfalls and solutions

**Time to read:** 10-15 minutes

---

### [DOCUMENTATION.md](DOCUMENTATION.md) - Complete Reference
**Who:** All users wanting comprehensive information
**What you'll learn:**
- All 13 brick types in detail
- Port system and connection validation
- Sequential workflow patterns
- Batch operations
- Advanced topics (restart, file retrieval, error handling)
- Complete working examples
- Architecture overview
- Best practices

**Time to read:** 45-60 minutes

**Key sections:**
- [Core Concepts](DOCUMENTATION.md#core-concepts) - Understanding the brick system
- [Brick Types](DOCUMENTATION.md#brick-types) - All 13 brick types explained
- [Sequential Workflows](DOCUMENTATION.md#sequential-workflows) - Multi-stage calculations
- [Batch Operations](DOCUMENTATION.md#batch-operations) - Parallel calculations
- [Examples](DOCUMENTATION.md#examples) - Working code samples
- [Advanced Topics](DOCUMENTATION.md#advanced-topics) - Power user features
- [Troubleshooting](DOCUMENTATION.md#troubleshooting) - Common issues

---

### [VISUAL_GUIDE.md](VISUAL_GUIDE.md) - Workflow Diagrams
**Who:** Visual learners, workflow designers
**What you'll learn:**
- Visual representation of all common workflows
- Mermaid diagrams showing data flow
- Connection patterns between bricks
- Parallel vs serial execution
- Complete workflow examples with diagrams

**Time to read:** 20-30 minutes

**Key sections:**
- [Basic Single Calculations](VISUAL_GUIDE.md#basic-single-calculations)
- [Sequential Workflows](VISUAL_GUIDE.md#sequential-workflows)
- [Batch Operations](VISUAL_GUIDE.md#batch-operations)
- [Advanced Multi-Stage Workflows](VISUAL_GUIDE.md#advanced-multi-stage-workflows)
- [NEB Calculations](VISUAL_GUIDE.md#neb-calculations)
- [Port Connection Patterns](VISUAL_GUIDE.md#port-connection-patterns)

---

### [AGENTS.md](AGENTS.md) - Developer Guide
**Who:** Contributors, developers, power users
**What you'll learn:**
- Package structure and architecture
- Testing strategy (tier1, tier2, tier3)
- Development workflow
- Adding new brick types
- Code style guidelines
- Cluster configuration

**Time to read:** 30-45 minutes

---

### [README.md](README.md) - API Reference
**Who:** Users needing function signatures
**What you'll learn:**
- Quick API overview
- Function signatures and parameters
- Module structure
- File retrieval defaults

**Time to read:** 15-20 minutes

---

## 🗺️ Learning Paths

### Path 1: "Just Get Started"
Perfect for when you need to run a calculation right now.

1. [QUICK_START.md](QUICK_START.md) → Your First Calculation
2. Try one of the examples in `examples/`
3. Come back to full docs when needed

**Time:** 10 minutes

---

### Path 2: "Comprehensive Learning"
Best for understanding the full system before writing code.

1. [QUICK_START.md](QUICK_START.md) → Installation & basics
2. [DOCUMENTATION.md](DOCUMENTATION.md) → Core Concepts section
3. [VISUAL_GUIDE.md](VISUAL_GUIDE.md) → See workflows visually
4. [DOCUMENTATION.md](DOCUMENTATION.md) → Specific brick types you need
5. Try examples in `examples/`
6. [DOCUMENTATION.md](DOCUMENTATION.md) → Advanced Topics as needed

**Time:** 2-3 hours

---

### Path 3: "Visual First"
Great for visual learners who learn best from diagrams.

1. [VISUAL_GUIDE.md](VISUAL_GUIDE.md) → Browse all diagrams
2. [QUICK_START.md](QUICK_START.md) → Try the code examples
3. [DOCUMENTATION.md](DOCUMENTATION.md) → Deep dive on specific topics
4. Explore `examples/` directory

**Time:** 1-2 hours

---

### Path 4: "Developer Onboarding"
For contributors or developers integrating Quantum Lego.

1. [README.md](README.md) → API overview
2. [AGENTS.md](AGENTS.md) → Package structure
3. [DOCUMENTATION.md](DOCUMENTATION.md) → Port system & bricks
4. [AGENTS.md](AGENTS.md) → Testing & development workflow
5. Study `quantum_lego/core/bricks/` source code

**Time:** 3-4 hours

---

## 🔍 Quick Reference by Task

### "I want to run a simple VASP calculation"
→ [QUICK_START.md - Your First Calculation](QUICK_START.md#your-first-calculation)

### "I need to calculate DOS"
→ [DOCUMENTATION.md - DOS Brick](DOCUMENTATION.md#2-dos-brick-dos)
→ [VISUAL_GUIDE.md - DOS Calculation](VISUAL_GUIDE.md#dos-calculation-two-step-process)

### "I want one WorkGraph with mixed structure sources"
→ [DOCUMENTATION.md - Mixed Structure Sources in One WorkGraph](DOCUMENTATION.md#mixed-structure-sources-in-one-workgraph)
→ Example script: `examples/vasp/run_mixed_dos_sources.py`

### "I need to run multiple structures"
→ [DOCUMENTATION.md - Batch Brick](DOCUMENTATION.md#3-batch-brick-batch)
→ [VISUAL_GUIDE.md - Batch Operations](VISUAL_GUIDE.md#batch-operations)

### "I want to chain calculations together"
→ [DOCUMENTATION.md - Sequential Workflows](DOCUMENTATION.md#sequential-workflows)
→ [VISUAL_GUIDE.md - Sequential Workflows](VISUAL_GUIDE.md#sequential-workflows)

### "I need to do NEB calculations"
→ [DOCUMENTATION.md - NEB Bricks](DOCUMENTATION.md#9-neb-bricks-generate_neb_images-neb)
→ [VISUAL_GUIDE.md - NEB Calculations](VISUAL_GUIDE.md#neb-calculations)

### "I want to do AIMD simulations"
→ [DOCUMENTATION.md - AIMD Brick](DOCUMENTATION.md#4-aimd-brick-aimd)

### "I need convergence testing"
→ [DOCUMENTATION.md - Convergence Brick](DOCUMENTATION.md#5-convergence-brick-convergence)
→ [VISUAL_GUIDE.md - Convergence Testing](VISUAL_GUIDE.md#convergence-testing)

### "I want Bader charge analysis"
→ [DOCUMENTATION.md - Bader Brick](DOCUMENTATION.md#7-bader-brick-bader)

### "I'm getting errors"
→ [DOCUMENTATION.md - Troubleshooting](DOCUMENTATION.md#troubleshooting)
→ [QUICK_START.md - Common Pitfalls](QUICK_START.md#common-pitfalls)

### "How do I monitor my calculations?"
→ [QUICK_START.md - Monitoring Commands](QUICK_START.md#monitoring-commands)

### "I want to add a new brick type"
→ [AGENTS.md - Adding a New Brick](AGENTS.md#adding-a-new-brick)

---

## 📊 Brick Type Quick Reference

Quick lookup table for all brick types:

| Brick Type | Use Case | Documentation | Visual |
|------------|----------|---------------|--------|
| `vasp` | Standard VASP calculations | [Docs](DOCUMENTATION.md#1-vasp-brick-vasp) | [Visual](VISUAL_GUIDE.md#simple-vasp-relaxation) |
| `dos` | Density of states | [Docs](DOCUMENTATION.md#2-dos-brick-dos) | [Visual](VISUAL_GUIDE.md#dos-calculation-two-step-process) |
| `batch` | Parallel calculations | [Docs](DOCUMENTATION.md#3-batch-brick-batch) | [Visual](VISUAL_GUIDE.md#batch-vasp-calculations) |
| `aimd` | Molecular dynamics | [Docs](DOCUMENTATION.md#4-aimd-brick-aimd) | - |
| `convergence` | Parameter testing | [Docs](DOCUMENTATION.md#5-convergence-brick-convergence) | [Visual](VISUAL_GUIDE.md#convergence-testing) |
| `thickness` | Slab convergence | [Docs](DOCUMENTATION.md#6-thickness-brick-thickness) | - |
| `bader` | Charge analysis | [Docs](DOCUMENTATION.md#7-bader-brick-bader) | [Visual](VISUAL_GUIDE.md#relaxation--bader-analysis) |
| `hubbard_response` | DFT+U response | [Docs](DOCUMENTATION.md#8-hubbard-u-bricks-hubbard_response-hubbard_analysis) | [Visual](VISUAL_GUIDE.md#hubbard-u-calculation) |
| `hubbard_analysis` | DFT+U analysis | [Docs](DOCUMENTATION.md#8-hubbard-u-bricks-hubbard_response-hubbard_analysis) | [Visual](VISUAL_GUIDE.md#hubbard-u-calculation) |
| `generate_neb_images` | NEB image generation | [Docs](DOCUMENTATION.md#9-neb-bricks-generate_neb_images-neb) | [Visual](VISUAL_GUIDE.md#complete-neb-workflow) |
| `neb` | Reaction pathways | [Docs](DOCUMENTATION.md#9-neb-bricks-generate_neb_images-neb) | [Visual](VISUAL_GUIDE.md#complete-neb-workflow) |
| `qe` | Quantum ESPRESSO | [Docs](DOCUMENTATION.md#10-qe-brick-qe) | - |
| `cp2k` | CP2K calculations | [Docs](DOCUMENTATION.md#11-cp2k-brick-cp2k) | - |

---

## 💡 Tips for Using the Documentation

### Search Effectively
- Use your browser's find function (Ctrl+F / Cmd+F)
- Search for INCAR parameters (e.g., "NSW", "IBRION")
- Search for error messages
- Search for brick types

### Follow Examples
- All examples are working code
- Examples directory: `examples/`
- Each brick type has at least one example
- Copy-paste and modify for your needs

### Use Mermaid Diagrams
- GitHub renders mermaid diagrams natively
- Diagrams show data flow and connections
- Color coding indicates brick types
- Follow the arrows to understand dependencies

### Keep Reference Handy
- Bookmark this index page
- Keep QUICK_START.md open while coding
- Reference DOCUMENTATION.md for details
- Use VISUAL_GUIDE.md to plan workflows

---

## 🆘 Getting Help

### Before Asking
1. Check [DOCUMENTATION.md - Troubleshooting](DOCUMENTATION.md#troubleshooting)
2. Check [QUICK_START.md - Common Pitfalls](QUICK_START.md#common-pitfalls)
3. Search this documentation
4. Try examples in `examples/` directory

### Where to Ask
- **GitHub Issues**: Bug reports, feature requests
- **Examples**: See `examples/` for working code patterns

### What to Include
- Quantum Lego version
- Python/AiiDA version
- Error message (full traceback)
- Minimal code example
- What you expected vs what happened

---

## 📦 Package Contents

```
quantum-lego/
├── README.md              ← API reference
├── DOCUMENTATION.md       ← Complete guide (this is the main doc)
├── QUICK_START.md         ← 5-minute tutorial
├── VISUAL_GUIDE.md        ← Workflow diagrams
├── AGENTS.md              ← Developer guide
├── DOC_INDEX.md           ← This file
├── quantum_lego/          ← Python package
│   └── core/
│       ├── bricks/        ← 13 brick types
│       ├── common/        ← Utilities
│       └── ...
├── examples/              ← Working examples
└── tests/                 ← Test suite
```

---

## 🎓 Learning Resources

### Conceptual Understanding
1. **Brick System**: [DOCUMENTATION.md - Core Concepts](DOCUMENTATION.md#core-concepts)
2. **Port Types**: [DOCUMENTATION.md - Port System](DOCUMENTATION.md#port-system)
3. **Connections**: [VISUAL_GUIDE.md - Port Connection Patterns](VISUAL_GUIDE.md#port-connection-patterns)

### Practical Skills
1. **First Calculation**: [QUICK_START.md](QUICK_START.md)
2. **Workflow Design**: [VISUAL_GUIDE.md](VISUAL_GUIDE.md)
3. **Advanced Features**: [DOCUMENTATION.md - Advanced Topics](DOCUMENTATION.md#advanced-topics)

### Technical Deep Dive
1. **Architecture**: [AGENTS.md - Package Structure](AGENTS.md#package-structure)
2. **Testing**: [AGENTS.md - Testing](AGENTS.md#testing)
3. **Contributing**: [AGENTS.md - Adding a New Brick](AGENTS.md#adding-a-new-brick)

---

## 📝 Documentation Versions

| File | Lines | Purpose | Last Updated |
|------|-------|---------|--------------|
| QUICK_START.md | 482 | Tutorial | 2026-02-10 |
| DOCUMENTATION.md | 1050 | Complete reference | 2026-02-10 |
| VISUAL_GUIDE.md | 624 | Diagrams | 2026-02-10 |
| AGENTS.md | 338 | Developer guide | 2026-02-10 |
| README.md | 411 | API reference | 2026-02-10 |

---

## ✨ What's Next?

After reading the documentation:

1. **Try Examples**: Run code in `examples/` directory
2. **Build Workflows**: Design your own multi-stage calculations
3. **Explore Bricks**: Try different brick types for your needs
4. **Optimize**: Use restart, parallel execution, and convergence testing
5. **Contribute**: Add new bricks or improve documentation

---

**Happy building with Quantum Lego! 🧱⚗️**

*Last updated: 2026-02-10*
