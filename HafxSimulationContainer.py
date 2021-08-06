import numpy as np
import os

import sim_src.impress_constants as ic
from sim_src.FlareSpectrum import FlareSpectrum
from HafxStack import HafxStack, SINGLE_DET_AREA

class HafxSimulationContainer:
    MIN_THRESHOLD_ENG = 8.0     # keV
    MAX_THRESHOLD_ENG = 100.0   # keV
    MIN_ENG = 1.0               # keV
    MAX_ENG = 300.0             # keV
    DE = 0.1                    # keV

    KAL_THICKNESS = 'al_thickness'
    KFLARE_THERMAL = 'thermal'
    KFLARE_NONTHERMAL = 'nonthermal'
    KENERGIES = 'energies'
    KPURE_RESPONSE = 'pure_response_matrix'
    KDISPERSED_RESPONSE = 'dispersed_response_matrix'
    KEFFECTIVE_AREA = 'effective_area'
    KGOES_CLASS = 'goes_class'
    MATRIX_KEYS = (
        KDISPERSED_RESPONSE, KPURE_RESPONSE
    )
    DEFAULT_SAVE_DIR = 'responses-and-areas'

    @classmethod
    def from_saved_file(cls, filename: str):
        ''' load the container from a (compressed) .npz file '''
        data = np.load(filename)

        try:
            goes_class = data[cls.KGOES_CLASS]
        except KeyError as e:
            goes_class = filename.split('_')[-3]
        fs = FlareSpectrum(
                goes_class,
                data[cls.KENERGIES],
                data[cls.KFLARE_THERMAL],
                data[cls.KFLARE_NONTHERMAL])

        ret = cls(aluminum_thickness=data[cls.KAL_THICKNESS], flare_spectrum=fs)
        ret.flare_spectrum = fs
        for k in cls.MATRIX_KEYS:
            ret.matrices[k] = data[k]
        return ret

    def __init__(self, aluminum_thickness: np.float64=None, flare_spectrum: FlareSpectrum=None):
        self.detector_stack = HafxStack()
        self.al_thick = aluminum_thickness
        self.matrices = {k: None for k in self.MATRIX_KEYS}
        self.flare_spectrum = flare_spectrum

    @property
    def al_thick(self):
        return self.__al_thick

    @al_thick.setter
    def al_thick(self, new):
        self.__al_thick = new
        self.detector_stack.materials[0].thickness = new

    def compute_effective_area(self, cps_threshold: np.int64=0):
        if cps_threshold > 0:
            restrict = np.logical_and(
                    self.flare_spectrum.energies >= self.MIN_THRESHOLD_ENG,
                    self.flare_spectrum.energies <= self.MAX_THRESHOLD_ENG)
            dispersed_flare = np.matmul(self.matrices[self.KDISPERSED_RESPONSE], self.flare_spectrum.flare)
            relevant_cps = np.trapz(
                dispersed_flare[restrict] * SINGLE_DET_AREA, x=self.flare_spectrum.energies[restrict])

            # "set" effective area to zero if we get more than the threshold counts
            if relevant_cps > cps_threshold:
                return np.zeros_like(self.flare_spectrum.energies)

        area_vector = np.ones_like(self.flare_spectrum.energies) * SINGLE_DET_AREA
        att_area = np.matmul(self.matrices[self.KPURE_RESPONSE], area_vector)
        return att_area

    def simulate(self):
        if self.al_thick is None:
            raise ValueError("Aluminum thickness has not been set.")
        # get the un-dispersed (pure) response matrix
        self.matrices[self.KPURE_RESPONSE] =\
                self \
                .detector_stack \
                .generate_detector_response_to(self.flare_spectrum, False) \
        # apply CeBr3 energy resolution
        self.matrices[self.KDISPERSED_RESPONSE] =\
                self \
                .detector_stack \
                .apply_detector_dispersion_for(self.flare_spectrum, self.matrices[self.KPURE_RESPONSE])

    def gen_file_name(self, prefix):
        gc = self.flare_spectrum.goes_class
        return f"{prefix or 'no_prefix'}_{gc or 'no_goes'}_{self.al_thick:.3e}cm_hafx"

    def save_to_file(self, out_dir=DEFAULT_SAVE_DIR, prefix=''):
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        ''' save object data into a file that can be loaded back in later '''
        if None in self.matrices:
            raise ValueError("Matrices haven't been computed so we can't save them.")
        if self.flare_spectrum is None:
            raise ValueError("Stored FlareSpectrum is None--simulation probably hasn't run.")

        to_save = dict()
        # maybe rethink what we save: really only need the GOES class and energy bounds/dE
        to_save[self.KAL_THICKNESS] = self.al_thick
        to_save[self.KFLARE_THERMAL] = self.flare_spectrum.thermal
        to_save[self.KFLARE_NONTHERMAL] = self.flare_spectrum.nonthermal
        to_save[self.KENERGIES] = self.flare_spectrum.energies

        for k in self.MATRIX_KEYS:
            to_save[k] = self.matrices[k]
        outfn = os.path.join(out_dir, self.gen_file_name(prefix))
        np.savez_compressed(outfn, **to_save)

