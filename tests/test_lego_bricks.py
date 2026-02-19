"""Unit tests for the lego brick registry and brick-level validate_stage() functions.

Also covers Bader file parsers: _parse_acf_dat() and _enrich_acf_dat().

All tests are tier1 (pure Python, no AiiDA profile needed).
"""

import os
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_vasp_stage():
    return {'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None}


@pytest.fixture
def valid_dos_stage():
    return {
        'name': 'dos_calc', 'type': 'dos',
        'scf_incar': {'encut': 400},
        'dos_incar': {'nedos': 2000},
        'structure_from': 'relax',
    }


@pytest.fixture
def valid_batch_stage():
    return {
        'name': 'fukui', 'type': 'batch',
        'structure_from': 'relax',
        'base_incar': {'NSW': 0},
        'calculations': {'neutral': {'incar': {'NELECT': 100}}},
    }


@pytest.fixture
def valid_bader_stage():
    return {'name': 'bader', 'type': 'bader', 'charge_from': 'relax'}


@pytest.fixture
def valid_generate_neb_images_stage():
    return {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 5,
        'method': 'idpp',
        'mic': True,
    }


@pytest.fixture
def valid_neb_stage():
    return {
        'name': 'neb_stage1',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'incar': {'encut': 520, 'ediff': 1e-6, 'ibrion': 3},
        'restart': None,
    }


@pytest.fixture
def valid_hubbard_response_stage():
    return {
        'name': 'response', 'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'input',
        'target_species': 'Ni',
    }


@pytest.fixture
def valid_hubbard_analysis_stage():
    return {
        'name': 'analysis', 'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'input',
        'target_species': 'Ni',
    }


@pytest.fixture
def sample_acf_dat_content():
    """Standard ACF.dat content with 2 atoms."""
    return (
        "    #         X           Y           Z        CHARGE     MIN DIST   ATOMIC VOL\n"
        " -----------------------------------------------------------------------\n"
        "    1      0.0000      0.0000      1.2345    6.5432      1.234     12.345\n"
        "    2      2.5000      2.5000      3.6789    8.7654      0.987     15.678\n"
        " -----------------------------------------------------------------------\n"
        "    NUMBER OF ELECTRONS:      15.30860\n"
        "    VACUUM CHARGE:             0.00000\n"
        "    VACUUM VOLUME:             0.00000\n"
    )


# ---------------------------------------------------------------------------
# TestBrickRegistry
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBrickRegistry:
    """Tests for BRICK_REGISTRY, VALID_BRICK_TYPES, get_brick_module()."""

    def test_valid_brick_types_tuple(self):
        from quantum_lego.core.bricks import VALID_BRICK_TYPES
        assert VALID_BRICK_TYPES == (
            'vasp', 'dimer', 'dos', 'hybrid_bands', 'batch', 'fukui_analysis',
            'birch_murnaghan', 'birch_murnaghan_refine', 'bader',
            'convergence', 'thickness', 'hubbard_response',
            'hubbard_analysis', 'aimd', 'qe', 'cp2k',
            'generate_neb_images', 'neb', 'surface_enumeration',
            'surface_terminations', 'dynamic_batch', 'formation_enthalpy',
            'o2_reference_energy', 'surface_gibbs_energy',
            'select_stable_surface', 'fukui_dynamic',
        )

    def test_registry_has_twenty_three_entries(self):
        from quantum_lego.core.bricks import BRICK_REGISTRY, VALID_BRICK_TYPES
        assert len(BRICK_REGISTRY) == len(VALID_BRICK_TYPES)

    def test_get_brick_module_valid_types(self):
        from quantum_lego.core.bricks import get_brick_module, VALID_BRICK_TYPES
        for brick_type in VALID_BRICK_TYPES:
            mod = get_brick_module(brick_type)
            assert mod is not None

    def test_each_brick_has_five_functions(self):
        from quantum_lego.core.bricks import get_brick_module, VALID_BRICK_TYPES
        required = (
            'validate_stage', 'create_stage_tasks', 'expose_stage_outputs',
            'get_stage_results', 'print_stage_results',
        )
        for brick_type in VALID_BRICK_TYPES:
            mod = get_brick_module(brick_type)
            for fn_name in required:
                assert callable(getattr(mod, fn_name, None)), \
                    f"{brick_type} module missing callable '{fn_name}'"

    def test_get_brick_module_invalid_raises(self):
        from quantum_lego.core.bricks import get_brick_module
        with pytest.raises(ValueError, match="Unknown brick type"):
            get_brick_module('invalid')

    def test_get_brick_module_empty_raises(self):
        from quantum_lego.core.bricks import get_brick_module
        with pytest.raises(ValueError):
            get_brick_module('')


# ---------------------------------------------------------------------------
# TestVaspValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestVaspValidateStage:
    """Tests for quantum_lego.core.bricks.vasp.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.vasp import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_minimal_passes(self, valid_vasp_stage):
        self._validate(valid_vasp_stage)

    def test_missing_incar_raises(self):
        stage = {'name': 'relax', 'restart': None}
        with pytest.raises(ValueError, match="incar"):
            self._validate(stage)

    def test_missing_restart_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}}
        with pytest.raises(ValueError, match="restart"):
            self._validate(stage)

    def test_restart_none_passes(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None}
        self._validate(stage)

    def test_restart_valid_stage_passes(self):
        stage = {'name': 'scf', 'incar': {'NSW': 0}, 'restart': 'relax'}
        self._validate(stage, stage_names={'relax'})

    def test_restart_unknown_stage_raises(self):
        stage = {'name': 'scf', 'incar': {'NSW': 0}, 'restart': 'nope'}
        with pytest.raises(ValueError, match="unknown"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_previous_passes(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'structure_from': 'previous'}
        self._validate(stage)

    def test_structure_from_input_passes(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'structure_from': 'input'}
        self._validate(stage)

    def test_structure_from_valid_name_passes(self):
        stage = {'name': 'scf', 'incar': {'NSW': 0}, 'restart': None, 'structure_from': 'relax'}
        self._validate(stage, stage_names={'relax'})

    def test_structure_from_invalid_raises(self):
        stage = {'name': 'scf', 'incar': {'NSW': 0}, 'restart': None, 'structure_from': 'unknown'}
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage)

    def test_supercell_valid_passes(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': [2, 2, 1]}
        self._validate(stage)

    def test_supercell_wrong_length_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': [2, 2]}
        with pytest.raises(ValueError, match="supercell"):
            self._validate(stage)

    def test_supercell_not_list_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': '2x2x1'}
        with pytest.raises(ValueError, match="supercell"):
            self._validate(stage)

    def test_supercell_zero_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': [2, 0, 1]}
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(stage)

    def test_supercell_negative_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': [2, -1, 1]}
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(stage)

    def test_supercell_float_raises(self):
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None, 'supercell': [2.0, 2, 1]}
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(stage)

    def test_fix_type_valid_passes(self):
        for fix_type in ('bottom', 'center', 'top'):
            stage = {
                'name': 'relax', 'incar': {'NSW': 100}, 'restart': None,
                'fix_type': fix_type, 'fix_thickness': 3.0,
            }
            self._validate(stage)

    def test_fix_type_invalid_raises(self):
        stage = {
            'name': 'relax', 'incar': {'NSW': 100}, 'restart': None,
            'fix_type': 'left', 'fix_thickness': 3.0,
        }
        with pytest.raises(ValueError, match="fix_type"):
            self._validate(stage)

    def test_fix_type_zero_thickness_raises(self):
        stage = {
            'name': 'relax', 'incar': {'NSW': 100}, 'restart': None,
            'fix_type': 'bottom', 'fix_thickness': 0,
        }
        with pytest.raises(ValueError, match="fix_thickness"):
            self._validate(stage)

    def test_fix_type_negative_thickness_raises(self):
        stage = {
            'name': 'relax', 'incar': {'NSW': 100}, 'restart': None,
            'fix_type': 'top', 'fix_thickness': -1,
        }
        with pytest.raises(ValueError, match="fix_thickness"):
            self._validate(stage)

    def test_fix_type_none_no_check(self):
        """When fix_type is not set, no thickness validation happens."""
        stage = {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None}
        self._validate(stage)  # no fix_thickness required


# ---------------------------------------------------------------------------
# TestDosValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestDosValidateStage:
    """Tests for quantum_lego.core.bricks.dos.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.dos import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_dos_stage):
        self._validate(valid_dos_stage, stage_names={'relax'})

    def test_missing_scf_incar_raises(self):
        stage = {'name': 'dos', 'dos_incar': {'nedos': 2000}, 'structure_from': 'relax'}
        with pytest.raises(ValueError, match="scf_incar"):
            self._validate(stage, stage_names={'relax'})

    def test_missing_dos_incar_raises(self):
        stage = {'name': 'dos', 'scf_incar': {'encut': 400}, 'structure_from': 'relax'}
        with pytest.raises(ValueError, match="dos_incar"):
            self._validate(stage, stage_names={'relax'})

    def test_missing_structure_source_raises(self):
        stage = {'name': 'dos', 'scf_incar': {'encut': 400}, 'dos_incar': {'nedos': 2000}}
        with pytest.raises(ValueError, match="structure source"):
            self._validate(stage)

    def test_explicit_structure_passes(self):
        stage = {
            'name': 'dos',
            'scf_incar': {'encut': 400},
            'dos_incar': {'nedos': 2000},
            'structure': object(),
        }
        self._validate(stage)

    def test_structure_and_structure_from_raises(self):
        stage = {
            'name': 'dos',
            'scf_incar': {'encut': 400},
            'dos_incar': {'nedos': 2000},
            'structure': object(),
            'structure_from': 'relax',
        }
        with pytest.raises(ValueError, match="either 'structure' or 'structure_from'"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_unknown_raises(self):
        stage = {
            'name': 'dos', 'scf_incar': {'encut': 400},
            'dos_incar': {'nedos': 2000}, 'structure_from': 'nope',
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_valid_passes(self):
        stage = {
            'name': 'dos', 'scf_incar': {'encut': 400},
            'dos_incar': {'nedos': 2000}, 'structure_from': 'relax',
        }
        self._validate(stage, stage_names={'relax'})


# ---------------------------------------------------------------------------
# TestBatchValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBatchValidateStage:
    """Tests for quantum_lego.core.bricks.batch.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.batch import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_batch_stage):
        self._validate(valid_batch_stage, stage_names={'relax'})

    def test_missing_structure_from_raises(self):
        stage = {
            'name': 'fukui',
            'base_incar': {'NSW': 0},
            'calculations': {'neutral': {'incar': {}}},
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage, stage_names={'relax'})

    def test_missing_base_incar_raises(self):
        stage = {
            'name': 'fukui', 'structure_from': 'relax',
            'calculations': {'neutral': {'incar': {}}},
        }
        with pytest.raises(ValueError, match="base_incar"):
            self._validate(stage, stage_names={'relax'})

    def test_missing_calculations_raises(self):
        stage = {
            'name': 'fukui', 'structure_from': 'relax',
            'base_incar': {'NSW': 0},
        }
        with pytest.raises(ValueError, match="calculations"):
            self._validate(stage, stage_names={'relax'})

    def test_empty_calculations_raises(self):
        stage = {
            'name': 'fukui', 'structure_from': 'relax',
            'base_incar': {'NSW': 0}, 'calculations': {},
        }
        with pytest.raises(ValueError, match="calculations"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_unknown_raises(self):
        stage = {
            'name': 'fukui', 'structure_from': 'nope',
            'base_incar': {'NSW': 0},
            'calculations': {'neutral': {'incar': {}}},
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_valid_passes(self):
        stage = {
            'name': 'fukui', 'structure_from': 'relax',
            'base_incar': {'NSW': 0},
            'calculations': {'neutral': {'incar': {}}},
        }
        self._validate(stage, stage_names={'relax'})


# ---------------------------------------------------------------------------
# TestBaderValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBaderValidateStage:
    """Tests for quantum_lego.core.bricks.bader.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.bader import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_bader_stage):
        self._validate(valid_bader_stage, stage_names={'relax'})

    def test_missing_charge_from_raises(self):
        stage = {'name': 'bader'}
        with pytest.raises(ValueError, match="charge_from"):
            self._validate(stage, stage_names={'relax'})

    def test_charge_from_unknown_raises(self):
        stage = {'name': 'bader', 'charge_from': 'nope'}
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax'})

    def test_charge_from_valid_passes(self):
        stage = {'name': 'bader', 'charge_from': 'relax'}
        self._validate(stage, stage_names={'relax'})


# ---------------------------------------------------------------------------
# TestGenerateNebImagesValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestGenerateNebImagesValidateStage:
    """Tests for quantum_lego.core.bricks.generate_neb_images.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.generate_neb_images import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_generate_neb_images_stage):
        self._validate(
            valid_generate_neb_images_stage,
            stage_names={'relax_initial', 'relax_final'},
        )

    def test_missing_initial_from_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'final_from': 'relax_final',
            'n_images': 5,
        }
        with pytest.raises(ValueError, match="initial_from"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_missing_final_from_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'n_images': 5,
        }
        with pytest.raises(ValueError, match="final_from"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_missing_n_images_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
        }
        with pytest.raises(ValueError, match="n_images"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_initial_from_unknown_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'unknown',
            'final_from': 'relax_final',
            'n_images': 5,
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_final_from_unknown_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'unknown',
            'n_images': 5,
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_n_images_zero_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'n_images': 0,
        }
        with pytest.raises(ValueError, match="positive integer"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_n_images_non_int_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'n_images': 2.5,
        }
        with pytest.raises(ValueError, match="positive integer"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_method_invalid_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'n_images': 5,
            'method': 'cubic',
        }
        with pytest.raises(ValueError, match="method"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_mic_non_bool_raises(self):
        stage = {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'n_images': 5,
            'mic': 1,
        }
        with pytest.raises(ValueError, match="mic"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})


# ---------------------------------------------------------------------------
# TestNebValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestNebValidateStage:
    """Tests for quantum_lego.core.bricks.neb.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.neb import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_with_images_from_passes(self, valid_neb_stage):
        self._validate(
            valid_neb_stage,
            stage_names={'relax_initial', 'relax_final', 'make_images'},
        )

    def test_valid_with_images_dir_passes(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_dir': './neb_images',
            'incar': {'encut': 520, 'ediff': 1e-6, 'ibrion': 3},
            'restart': None,
        }
        self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_missing_initial_from_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="initial_from"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})

    def test_missing_final_from_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'images_from': 'make_images',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="final_from"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})

    def test_missing_incar_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
        }
        with pytest.raises(ValueError, match="incar"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})

    def test_incar_not_dict_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'incar': 'encut=520',
        }
        with pytest.raises(ValueError, match="incar"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})

    def test_missing_both_image_sources_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="exactly one"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_both_image_sources_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'images_dir': './neb_images',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="exactly one"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})

    def test_images_from_unknown_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'unknown',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_images_dir_empty_raises(self):
        stage = {
            'name': 'neb_stage1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_dir': '',
            'incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="images_dir"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final'})

    def test_restart_unknown_raises(self):
        stage = {
            'name': 'neb_stage2',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'incar': {'encut': 520},
            'restart': 'unknown',
        }
        with pytest.raises(ValueError, match="previous stage"):
            self._validate(stage, stage_names={'relax_initial', 'relax_final', 'make_images'})


# ---------------------------------------------------------------------------
# TestNebLclimbHandling
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestNebLclimbHandling:
    """Tests for NEB LCLIMB compatibility helpers."""

    def test_extract_lclimb_from_incar_removes_key_and_returns_bool(self):
        from quantum_lego.core.bricks.neb import _extract_lclimb_from_incar

        clean_incar, lclimb = _extract_lclimb_from_incar(
            {'encut': 520, 'ibrion': 3, 'lclimb': True}
        )

        assert lclimb is True
        assert 'lclimb' not in clean_incar
        assert clean_incar['encut'] == 520

    def test_extract_lclimb_from_incar_accepts_string_bool(self):
        from quantum_lego.core.bricks.neb import _extract_lclimb_from_incar

        clean_incar, lclimb = _extract_lclimb_from_incar(
            {'encut': 520, 'LCLIMB': '.TRUE.'}
        )

        assert lclimb is True
        assert 'LCLIMB' not in clean_incar

    def test_extract_lclimb_from_incar_invalid_value_raises(self):
        from quantum_lego.core.bricks.neb import _extract_lclimb_from_incar

        with pytest.raises(ValueError, match="LCLIMB"):
            _extract_lclimb_from_incar({'encut': 520, 'lclimb': [1]})

    def test_inject_lclimb_prepend_text_appends_command(self):
        from quantum_lego.core.bricks.neb import _inject_lclimb_prepend_text

        options = {'resources': {'num_machines': 1}, 'prepend_text': 'module load vasp'}
        updated = _inject_lclimb_prepend_text(options, True)

        assert 'prepend_text' in updated
        assert 'module load vasp' in updated['prepend_text']
        assert 'echo LCLIMB=.TRUE. >> INCAR' in updated['prepend_text']

    def test_inject_lclimb_prepend_text_none_keeps_options(self):
        from quantum_lego.core.bricks.neb import _inject_lclimb_prepend_text

        options = {'resources': {'num_machines': 1}}
        updated = _inject_lclimb_prepend_text(options, None)

        assert updated == options

    def test_build_neb_parser_settings_includes_required_outputs(self):
        from quantum_lego.core.bricks.neb import _build_neb_parser_settings

        settings = _build_neb_parser_settings()
        parser = settings['parser_settings']

        assert parser['add_energy'] is True
        assert parser['add_trajectory'] is True
        assert parser['add_structure'] is True
        assert parser['add_kpoints'] is True
        assert 'trajectory' in parser['include_node']
        assert 'structure' in parser['include_node']
        assert 'kpoints' in parser['include_node']

    def test_build_neb_parser_settings_preserves_existing_entries(self):
        from quantum_lego.core.bricks.neb import _build_neb_parser_settings

        settings = _build_neb_parser_settings(
            {'parser_settings': {'check_errors': False, 'include_node': ['dos']}}
        )
        parser = settings['parser_settings']

        assert parser['check_errors'] is False
        assert 'dos' in parser['include_node']

    def test_build_kpoints_from_spacing_returns_kpointsdata(self):
        from aiida import orm
        from quantum_lego.core.bricks.neb import build_kpoints_from_spacing

        structure = orm.StructureData(
            cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]]
        )
        structure.append_atom(position=(0.0, 0.0, 0.0), symbols='Sn')
        structure.append_atom(position=(1.5, 1.5, 1.5), symbols='O')
        result = build_kpoints_from_spacing._callable(structure, orm.Float(0.04))

        assert isinstance(result, orm.KpointsData)
        mesh, _ = result.get_kpoints_mesh()
        assert len(mesh) == 3
        assert all(isinstance(v, int) and v > 0 for v in mesh)


# ---------------------------------------------------------------------------
# TestParseAcfDat
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestParseAcfDat:
    """Tests for quantum_lego.core.bricks.bader._parse_acf_dat()."""

    def _parse(self, filepath):
        from quantum_lego.core.bricks.bader import _parse_acf_dat
        return _parse_acf_dat(filepath)

    def test_parses_two_atoms(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        result = self._parse(str(acf))
        assert len(result['atoms']) == 2

    def test_atom_fields_present(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        result = self._parse(str(acf))
        expected_keys = {'index', 'x', 'y', 'z', 'charge', 'min_dist', 'volume'}
        for atom in result['atoms']:
            assert expected_keys.issubset(atom.keys())

    def test_atom_values_correct(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        result = self._parse(str(acf))
        atom0 = result['atoms'][0]
        assert atom0['charge'] == pytest.approx(6.5432)
        assert atom0['x'] == pytest.approx(0.0)
        assert atom0['y'] == pytest.approx(0.0)
        assert atom0['z'] == pytest.approx(1.2345)

    def test_total_electrons(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        result = self._parse(str(acf))
        assert result['total_charge'] == pytest.approx(15.30860)

    def test_vacuum_values(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        result = self._parse(str(acf))
        assert result['vacuum_charge'] == pytest.approx(0.0)
        assert result['vacuum_volume'] == pytest.approx(0.0)

    def test_empty_file(self, tmp_path):
        acf = tmp_path / 'ACF.dat'
        acf.write_text('')
        result = self._parse(str(acf))
        assert result['atoms'] == []
        assert result['total_charge'] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestEnrichAcfDat
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestEnrichAcfDat:
    """Tests for quantum_lego.core.bricks.bader._enrich_acf_dat()."""

    def _enrich(self, filepath, elements, zval_dict):
        from quantum_lego.core.bricks.bader import _enrich_acf_dat
        _enrich_acf_dat(filepath, elements, zval_dict)

    def test_header_has_new_columns(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        self._enrich(str(acf), ['Sn', 'O'], {'Sn': 14.0, 'O': 6.0})
        lines = acf.read_text().splitlines()
        header = lines[0]
        assert 'ELEMENT' in header
        assert 'VALENCE' in header
        assert 'BADER_CHARGE' in header

    def test_correct_element_assignment(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        self._enrich(str(acf), ['Sn', 'O'], {'Sn': 14.0, 'O': 6.0})
        text = acf.read_text()
        assert 'Sn' in text
        assert 'O' in text

    def test_bader_charge_calculation(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        self._enrich(str(acf), ['Sn', 'O'], {'Sn': 14.0, 'O': 6.0})
        lines = acf.read_text().splitlines()
        # Atom 1: VALENCE=14.0, CHARGE=6.5432 → BADER_CHARGE = 14.0 - 6.5432 = 7.4568
        atom1_line = lines[2]  # skip header + separator
        assert '7.4568' in atom1_line
        # Atom 2: VALENCE=6.0, CHARGE=8.7654 → BADER_CHARGE = 6.0 - 8.7654 = -2.7654
        atom2_line = lines[3]
        assert '-2.7654' in atom2_line

    def test_summary_lines_preserved(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        self._enrich(str(acf), ['Sn', 'O'], {'Sn': 14.0, 'O': 6.0})
        text = acf.read_text()
        assert 'NUMBER OF ELECTRONS' in text

    def test_empty_zval_dict(self, tmp_path, sample_acf_dat_content):
        acf = tmp_path / 'ACF.dat'
        acf.write_text(sample_acf_dat_content)
        self._enrich(str(acf), ['Sn', 'O'], {})
        lines = acf.read_text().splitlines()
        # valence=0.0, bader_charge = 0.0 - charge = -charge
        # Atom 1: bader_charge = 0 - 6.5432 = -6.5432
        atom1_line = lines[2]
        assert '-6.5432' in atom1_line


# ---------------------------------------------------------------------------
# TestHubbardResponseValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestHubbardResponseValidateStage:
    """Tests for quantum_lego.core.bricks.hubbard_response.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.hubbard_response import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_hubbard_response_stage):
        self._validate(valid_hubbard_response_stage,
                       stage_names={'ground_state'})

    def test_valid_with_input_structure(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Fe',
        }
        self._validate(stage, stage_names={'gs'})

    def test_valid_with_custom_potentials(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
            'potential_values': [-0.3, -0.15, 0.15, 0.3],
        }
        self._validate(stage, stage_names={'gs'})

    def test_valid_with_ldaul_3(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ce',
            'ldaul': 3,
        }
        self._validate(stage, stage_names={'gs'})

    def test_missing_target_species_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
        }
        with pytest.raises(ValueError, match="target_species"):
            self._validate(stage, stage_names={'gs'})

    def test_missing_ground_state_from_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'structure_from': 'input',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="ground_state_from"):
            self._validate(stage)

    def test_ground_state_from_unknown_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'nope',
            'structure_from': 'input',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'gs'})

    def test_missing_structure_from_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage, stage_names={'gs'})

    def test_structure_from_unknown_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'nope',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'gs'})

    def test_potential_values_with_zero_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
            'potential_values': [-0.2, 0.0, 0.2],
        }
        with pytest.raises(ValueError, match="must not include 0.0"):
            self._validate(stage, stage_names={'gs'})

    def test_potential_values_too_few_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
            'potential_values': [0.1],
        }
        with pytest.raises(ValueError, match="at least 2"):
            self._validate(stage, stage_names={'gs'})

    def test_potential_values_not_list_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
            'potential_values': 0.1,
        }
        with pytest.raises(ValueError, match="list of floats"):
            self._validate(stage, stage_names={'gs'})

    def test_ldaul_invalid_raises(self):
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
            'ldaul': 1,
        }
        with pytest.raises(ValueError, match="ldaul"):
            self._validate(stage, stage_names={'gs'})

    def test_default_potential_values_not_validated(self):
        """When potential_values is not provided, no validation on them."""
        stage = {
            'name': 'response', 'type': 'hubbard_response',
            'ground_state_from': 'gs',
            'structure_from': 'input',
            'target_species': 'Ni',
        }
        self._validate(stage, stage_names={'gs'})  # should not raise


# ---------------------------------------------------------------------------
# TestHubbardAnalysisValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestHubbardAnalysisValidateStage:
    """Tests for quantum_lego.core.bricks.hubbard_analysis.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.hubbard_analysis import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, valid_hubbard_analysis_stage):
        self._validate(valid_hubbard_analysis_stage,
                       stage_names={'response'})

    def test_missing_response_from_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'structure_from': 'input',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="response_from"):
            self._validate(stage)

    def test_response_from_unknown_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'nope',
            'structure_from': 'input',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'response'})

    def test_missing_target_species_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'response',
            'structure_from': 'input',
        }
        with pytest.raises(ValueError, match="target_species"):
            self._validate(stage, stage_names={'response'})

    def test_missing_structure_from_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'response',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage, stage_names={'response'})

    def test_structure_from_unknown_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'response',
            'structure_from': 'nope',
            'target_species': 'Ni',
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'response'})

    def test_ldaul_invalid_raises(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'response',
            'structure_from': 'input',
            'target_species': 'Ni',
            'ldaul': 1,
        }
        with pytest.raises(ValueError, match="ldaul"):
            self._validate(stage, stage_names={'response'})

    def test_valid_with_ldaul_3(self):
        stage = {
            'name': 'analysis', 'type': 'hubbard_analysis',
            'response_from': 'response',
            'structure_from': 'input',
            'target_species': 'Ce',
            'ldaul': 3,
        }
        self._validate(stage, stage_names={'response'})


# ---------------------------------------------------------------------------
# TestAimdValidateStage
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_aimd_stage():
    return {
        'name': 'equilibration', 'type': 'aimd',
        'tebeg': 300, 'nsw': 100, 'restart': None,
    }


@pytest.mark.tier1
class TestAimdValidateStage:
    """Tests for quantum_lego.core.bricks.aimd.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.aimd import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_minimal_passes(self, valid_aimd_stage):
        self._validate(valid_aimd_stage)

    def test_valid_full_config_passes(self):
        stage = {
            'name': 'prod', 'type': 'aimd',
            'tebeg': 600, 'nsw': 5000, 'teend': 300,
            'potim': 1.5, 'mdalgo': 2, 'smass': 0.0,
            'restart': None,
            'incar': {'encut': 400, 'ediff': 1e-5},
        }
        self._validate(stage)

    def test_missing_tebeg_raises(self):
        stage = {'name': 'md', 'nsw': 100, 'restart': None}
        with pytest.raises(ValueError, match="tebeg"):
            self._validate(stage)

    def test_missing_nsw_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'restart': None}
        with pytest.raises(ValueError, match="nsw"):
            self._validate(stage)

    def test_missing_restart_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'nsw': 100}
        with pytest.raises(ValueError, match="restart"):
            self._validate(stage)

    def test_tebeg_zero_raises(self):
        stage = {'name': 'md', 'tebeg': 0, 'nsw': 100, 'restart': None}
        with pytest.raises(ValueError, match="tebeg"):
            self._validate(stage)

    def test_tebeg_negative_raises(self):
        stage = {'name': 'md', 'tebeg': -100, 'nsw': 100, 'restart': None}
        with pytest.raises(ValueError, match="tebeg"):
            self._validate(stage)

    def test_nsw_zero_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'nsw': 0, 'restart': None}
        with pytest.raises(ValueError, match="nsw"):
            self._validate(stage)

    def test_nsw_negative_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'nsw': -10, 'restart': None}
        with pytest.raises(ValueError, match="nsw"):
            self._validate(stage)

    def test_potim_zero_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'nsw': 100, 'potim': 0, 'restart': None}
        with pytest.raises(ValueError, match="potim"):
            self._validate(stage)

    def test_potim_negative_raises(self):
        stage = {'name': 'md', 'tebeg': 300, 'nsw': 100, 'potim': -1, 'restart': None}
        with pytest.raises(ValueError, match="potim"):
            self._validate(stage)

    def test_restart_none_passes(self, valid_aimd_stage):
        self._validate(valid_aimd_stage)

    def test_restart_valid_stage_passes(self):
        stage = {'name': 'prod', 'tebeg': 300, 'nsw': 500, 'restart': 'equil'}
        self._validate(stage, stage_names={'equil'})

    def test_restart_unknown_stage_raises(self):
        stage = {'name': 'prod', 'tebeg': 300, 'nsw': 500, 'restart': 'nope'}
        with pytest.raises(ValueError, match="unknown"):
            self._validate(stage, stage_names={'equil'})

    def test_structure_from_previous_passes(self, valid_aimd_stage):
        valid_aimd_stage['structure_from'] = 'previous'
        self._validate(valid_aimd_stage)

    def test_structure_from_input_passes(self, valid_aimd_stage):
        valid_aimd_stage['structure_from'] = 'input'
        self._validate(valid_aimd_stage)

    def test_structure_from_valid_name_passes(self):
        stage = {
            'name': 'md', 'tebeg': 300, 'nsw': 100,
            'restart': None, 'structure_from': 'relax',
        }
        self._validate(stage, stage_names={'relax'})

    def test_structure_from_invalid_raises(self):
        stage = {
            'name': 'md', 'tebeg': 300, 'nsw': 100,
            'restart': None, 'structure_from': 'unknown',
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage)

    def test_supercell_valid_passes(self, valid_aimd_stage):
        valid_aimd_stage['supercell'] = [2, 2, 1]
        self._validate(valid_aimd_stage)

    def test_supercell_wrong_length_raises(self, valid_aimd_stage):
        valid_aimd_stage['supercell'] = [2, 2]
        with pytest.raises(ValueError, match="supercell"):
            self._validate(valid_aimd_stage)

    def test_supercell_zero_raises(self, valid_aimd_stage):
        valid_aimd_stage['supercell'] = [2, 0, 1]
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(valid_aimd_stage)

    def test_supercell_float_raises(self, valid_aimd_stage):
        valid_aimd_stage['supercell'] = [2.0, 2, 1]
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(valid_aimd_stage)


# ---------------------------------------------------------------------------
# TestAimdParserSettings
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestAimdParserSettings:
    """Tests for AIMD parser settings helper."""

    def test_include_node_contains_trajectory_structure_kpoints(self):
        from quantum_lego.core.bricks.aimd import _build_aimd_parser_settings

        settings = _build_aimd_parser_settings()
        include_node = settings.get('include_node', [])

        assert 'trajectory' in include_node
        assert 'structure' in include_node
        assert 'kpoints' in include_node

    def test_preserves_existing_parser_entries(self):
        from quantum_lego.core.bricks.aimd import _build_aimd_parser_settings

        settings = _build_aimd_parser_settings({'check_errors': False, 'include_node': ['dos']})

        assert settings['check_errors'] is False
        assert 'dos' in settings['include_node']

# ---------------------------------------------------------------------------
# TestQeValidateStage
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_qe_stage():
    return {
        'name': 'relax',
        'type': 'qe',
        'parameters': {
            'CONTROL': {'calculation': 'relax'},
            'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
            'ELECTRONS': {'conv_thr': 1e-8},
        },
        'restart': None,
    }


@pytest.mark.tier1
class TestQeValidateStage:
    """Tests for quantum_lego.core.bricks.qe.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.qe import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_minimal_passes(self, valid_qe_stage):
        self._validate(valid_qe_stage)

    def test_missing_parameters_raises(self):
        stage = {'name': 'relax', 'restart': None}
        with pytest.raises(ValueError, match="parameters"):
            self._validate(stage)

    def test_missing_restart_raises(self):
        stage = {
            'name': 'relax',
            'parameters': {'CONTROL': {'calculation': 'relax'}},
        }
        with pytest.raises(ValueError, match="restart"):
            self._validate(stage)

    def test_restart_none_passes(self):
        stage = {
            'name': 'relax',
            'parameters': {'CONTROL': {'calculation': 'relax'}},
            'restart': None,
        }
        self._validate(stage)

    def test_restart_valid_stage_passes(self):
        stage = {
            'name': 'scf',
            'parameters': {'CONTROL': {'calculation': 'scf'}},
            'restart': 'relax',
        }
        self._validate(stage, stage_names={'relax'})

    def test_restart_unknown_stage_raises(self):
        stage = {
            'name': 'scf',
            'parameters': {'CONTROL': {'calculation': 'scf'}},
            'restart': 'nope',
        }
        with pytest.raises(ValueError, match="unknown"):
            self._validate(stage, stage_names={'relax'})

    def test_structure_from_previous_passes(self):
        stage = {
            'name': 'relax',
            'parameters': {'CONTROL': {'calculation': 'relax'}},
            'restart': None,
            'structure_from': 'previous',
        }
        self._validate(stage)

    def test_structure_from_input_passes(self):
        stage = {
            'name': 'relax',
            'parameters': {'CONTROL': {'calculation': 'relax'}},
            'restart': None,
            'structure_from': 'input',
        }
        self._validate(stage)

    def test_structure_from_valid_name_passes(self):
        stage = {
            'name': 'scf',
            'parameters': {'CONTROL': {'calculation': 'scf'}},
            'restart': None,
            'structure_from': 'relax',
        }
        self._validate(stage, stage_names={'relax'})

    def test_structure_from_invalid_raises(self):
        stage = {
            'name': 'scf',
            'parameters': {'CONTROL': {'calculation': 'scf'}},
            'restart': None,
            'structure_from': 'unknown',
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage)


# ---------------------------------------------------------------------------
# TestCp2kValidateStage
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_cp2k_stage():
    return {
        'name': 'geo_opt',
        'type': 'cp2k',
        'parameters': {
            'GLOBAL': {'RUN_TYPE': 'GEO_OPT'},
            'FORCE_EVAL': {
                'METHOD': 'QUICKSTEP',
                'DFT': {
                    'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                    'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                },
            },
        },
        'restart': None,
        'file': {
            'basis': '/path/to/BASIS_MOLOPT',
            'pseudo': '/path/to/GTH_POTENTIALS',
        },
    }


@pytest.mark.tier1
class TestCp2kValidateStage:
    """Tests for quantum_lego.core.bricks.cp2k.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.cp2k import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_minimal_passes(self, valid_cp2k_stage):
        self._validate(valid_cp2k_stage)

    def test_valid_with_basis_pseudo_files_passes(self):
        stage = {
            'name': 'geo_opt',
            'type': 'cp2k',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'basis_file': '/path/to/BASIS_MOLOPT',
            'pseudo_file': '/path/to/GTH_POTENTIALS',
        }
        self._validate(stage)

    def test_missing_parameters_raises(self):
        stage = {
            'name': 'geo_opt',
            'restart': None,
            'file': {'basis': '/path/b', 'pseudo': '/path/p'},
        }
        with pytest.raises(ValueError, match="parameters"):
            self._validate(stage)

    def test_missing_restart_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'file': {'basis': '/path/b', 'pseudo': '/path/p'},
        }
        with pytest.raises(ValueError, match="restart"):
            self._validate(stage)

    def test_missing_file_and_basis_pseudo_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
        }
        with pytest.raises(ValueError, match="file.*basis_file.*pseudo_file"):
            self._validate(stage)

    def test_missing_pseudo_file_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'basis_file': '/path/to/BASIS_MOLOPT',
        }
        with pytest.raises(ValueError, match="file.*basis_file.*pseudo_file"):
            self._validate(stage)

    def test_missing_basis_file_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'pseudo_file': '/path/to/GTH_POTENTIALS',
        }
        with pytest.raises(ValueError, match="file.*basis_file.*pseudo_file"):
            self._validate(stage)

    def test_file_dict_missing_basis_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'file': {'pseudo': '/path/p'},
        }
        with pytest.raises(ValueError, match="basis.*pseudo"):
            self._validate(stage)

    def test_file_dict_missing_pseudo_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'file': {'basis': '/path/b'},
        }
        with pytest.raises(ValueError, match="basis.*pseudo"):
            self._validate(stage)

    def test_file_not_dict_raises(self):
        stage = {
            'name': 'geo_opt',
            'parameters': {'GLOBAL': {'RUN_TYPE': 'GEO_OPT'}},
            'restart': None,
            'file': '/path/to/file',
        }
        with pytest.raises(ValueError, match="file.*must be a dict"):
            self._validate(stage)

    def test_restart_none_passes(self, valid_cp2k_stage):
        self._validate(valid_cp2k_stage)

    def test_restart_valid_stage_passes(self, valid_cp2k_stage):
        valid_cp2k_stage['restart'] = 'prev_stage'
        self._validate(valid_cp2k_stage, stage_names={'prev_stage'})

    def test_restart_unknown_stage_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['restart'] = 'nope'
        with pytest.raises(ValueError, match="unknown"):
            self._validate(valid_cp2k_stage, stage_names={'other'})

    def test_structure_from_previous_passes(self, valid_cp2k_stage):
        valid_cp2k_stage['structure_from'] = 'previous'
        self._validate(valid_cp2k_stage)

    def test_structure_from_input_passes(self, valid_cp2k_stage):
        valid_cp2k_stage['structure_from'] = 'input'
        self._validate(valid_cp2k_stage)

    def test_structure_from_valid_name_passes(self, valid_cp2k_stage):
        valid_cp2k_stage['structure_from'] = 'relax'
        self._validate(valid_cp2k_stage, stage_names={'relax'})

    def test_structure_from_invalid_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['structure_from'] = 'unknown'
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(valid_cp2k_stage)

    def test_fix_type_valid_passes(self, valid_cp2k_stage):
        for fix_type in ('bottom', 'center', 'top'):
            valid_cp2k_stage['fix_type'] = fix_type
            valid_cp2k_stage['fix_thickness'] = 3.0
            self._validate(valid_cp2k_stage)

    def test_fix_type_invalid_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['fix_type'] = 'left'
        valid_cp2k_stage['fix_thickness'] = 3.0
        with pytest.raises(ValueError, match="fix_type"):
            self._validate(valid_cp2k_stage)

    def test_fix_type_zero_thickness_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['fix_type'] = 'bottom'
        valid_cp2k_stage['fix_thickness'] = 0
        with pytest.raises(ValueError, match="fix_thickness"):
            self._validate(valid_cp2k_stage)

    def test_fix_type_negative_thickness_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['fix_type'] = 'top'
        valid_cp2k_stage['fix_thickness'] = -1
        with pytest.raises(ValueError, match="fix_thickness"):
            self._validate(valid_cp2k_stage)

    def test_fix_type_none_no_check(self, valid_cp2k_stage):
        """When fix_type is not set, no thickness validation happens."""
        self._validate(valid_cp2k_stage)

    def test_supercell_valid_passes(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = [2, 2, 1]
        self._validate(valid_cp2k_stage)

    def test_supercell_wrong_length_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = [2, 2]
        with pytest.raises(ValueError, match="supercell"):
            self._validate(valid_cp2k_stage)

    def test_supercell_not_list_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = '2x2x1'
        with pytest.raises(ValueError, match="supercell"):
            self._validate(valid_cp2k_stage)

    def test_supercell_zero_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = [2, 0, 1]
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(valid_cp2k_stage)

    def test_supercell_negative_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = [2, -1, 1]
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(valid_cp2k_stage)

    def test_supercell_float_raises(self, valid_cp2k_stage):
        valid_cp2k_stage['supercell'] = [2.0, 2, 1]
        with pytest.raises(ValueError, match="positive integers"):
            self._validate(valid_cp2k_stage)
