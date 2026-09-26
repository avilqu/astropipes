''' Calibrator class definition (creation, storage and use of bias, dark and flat calibration masters)
    @author: Adrien Vilquin Barrajon <avilqu@gmail.com>
'''

from pathlib import Path
from datetime import datetime
import shutil
import glob
import os

from astropy import units as u
import ccdproc as ccdp
from colorama import Fore, Style
from astropy.io import fits

from lib.legacy.class_fits_sequence import FITSSequence
import config as cfg
import lib.legacy.helpers as hlp


write_path = Path(f'{os.getcwd()}/calibrated')
write_path.mkdir(exist_ok=True)


class Calibrator:

    def __init__(self, data=None):
        self.master_files = []

        for file in glob.glob(f'{cfg.CALIBRATION_PATH}/*.fits'):
            self.master_files.append(file)
        self.masters = FITSSequence(self.master_files)

        self.biases = []
        self.darks = []
        self.flats = []

        for file in self.masters.files:
            if file['header']['FRAME'] == 'Bias':
                self.biases.append(file)
            if file['header']['FRAME'] == 'Dark':
                self.darks.append(file)
            if file['header']['FRAME'] == 'Flat':
                self.flats.append(file)

    def generate_master_bias(self, seq):
        ''' Generates a master bias from the input FITS sequence 

            :param seq: FITSSequence object
            :return: True if successful
        '''

        print(
            f'\n{Style.BRIGHT}Generating master bias from {len(seq.filenames)} files.{Style.RESET_ALL}')
        hlp.prompt()

        stack = seq.integrate_sequence(confirm=False)

        ccd_temp = str(round(stack.header['CCD-TEMP']))
        date_obs = datetime.strptime(
            stack.header['DATE-OBS'], '%Y-%m-%dT%H:%M:%S.%f')
        date_string = date_obs.strftime('%Y%m%d')
        gain = str(round(stack.header['GAIN']))
        offset = str(round(stack.header['OFFSET']))
        binning = str(stack.header['XBINNING']) + \
            'x' + str(stack.header['XBINNING'])
        filename = f'master_bias_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits'

        stack.meta['IMAGETYP'] = 'Master Bias'

        print(f'Writing {cfg.CALIBRATION_PATH}/{filename}...')
        stack.write(f'{cfg.CALIBRATION_PATH}/{filename}', overwrite=True)
        shutil.rmtree(f'{os.getcwd()}/calibrated/')

        return True

    def generate_master_dark(self, seq):
        ''' Generates a calibrated master dark (bias subtracted)
            from the input FITS sequence 

            :param seq: FITSSequence object
            :return: True if success, False if failure
        '''

        print(
            f'\n{Style.BRIGHT}Generating master dark from {len(seq.filenames)} files.{Style.RESET_ALL}')
        hlp.prompt()

        print(
            f'\n{Style.BRIGHT}Calibrating {len(seq.filenames)} files.{Style.RESET_ALL}...')
        for image in seq.files:
            filename = image['filename']
            print(f'\n{Style.BRIGHT}Calibrating {filename}...{Style.RESET_ALL}')
            hlp.header_summary(image)

            master_bias = self.filter_masters(
                image, 'Bias', cfg.BIAS_CONSTRAINTS)
            if not master_bias:
                print(
                    f'{Style.BRIGHT + Fore.RED}Cannot generate master dark{Style.RESET_ALL}')
                return False

            calibrated_image = self.subtract_bias(image, master_bias)

            new_filename = f'b_{filename}'
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)

        calibrated_files = []
        for file in glob.glob(f'{write_path}/*.fits'):
            calibrated_files.append(file)
        calibrated_sequence = FITSSequence(calibrated_files)

        stack = calibrated_sequence.integrate_sequence(confirm=False)

        exptime = str(round(stack.header['EXPTIME']))
        ccd_temp = str(round(stack.header['CCD-TEMP']))
        date_obs = datetime.strptime(
            stack.header['DATE-OBS'], '%Y-%m-%dT%H:%M:%S.%f')
        date_string = date_obs.strftime('%Y%m%d')
        gain = str(round(stack.header['GAIN']))
        offset = str(round(stack.header['OFFSET']))
        binning = str(stack.header['XBINNING']) + \
            'x' + str(stack.header['XBINNING'])
        filename = f'master_dark_{exptime}_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits'

        stack.meta['IMAGETYP'] = 'Master Dark'

        print(f'Writing {cfg.CALIBRATION_PATH}/{filename}...')
        stack.write(f'{cfg.CALIBRATION_PATH}/{filename}', overwrite=True)
        shutil.rmtree(f'{os.getcwd()}/calibrated/')

        return True

    def generate_master_flat(self, seq):
        ''' Generates a master flat from the input FITS sequence 

            :param seq: FITSSequence object
            :return: True if success, False if failure
        '''

        print(
            f'\n{Style.BRIGHT}Generating master flat from {len(seq.filenames)} files.{Style.RESET_ALL}')
        hlp.prompt()

        print(
            f'\n{Style.BRIGHT}Calibrating {len(seq.filenames)} files.{Style.RESET_ALL}...')
        for image in seq.files:
            filename = image['filename']
            print(f'\n{Style.BRIGHT}Calibrating {filename}...{Style.RESET_ALL}')
            hlp.header_summary(image)

            master_bias = self.filter_masters(
                image, 'Bias', cfg.BIAS_CONSTRAINTS)
            if not master_bias:
                print(
                    f'{Style.BRIGHT + Fore.RED}Could not generate master flat!{Style.RESET_ALL}')
                return False

            calibrated_image = self.subtract_bias(image, master_bias)

            master_dark = self.filter_masters(
                image, 'Dark', cfg.DARK_CONSTRAINTS)
            if not master_dark:
                print(
                    f'{Style.BRIGHT + Fore.RED}Could not generate master flat!{Style.RESET_ALL}')
                return False

            calibrated_image = self.subtract_dark(
                calibrated_image, master_dark)

            new_filename = f'b_d_{filename}'
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)

        calibrated_files = []
        for file in glob.glob(f'{write_path}/*.fits'):
            calibrated_files.append(file)
        calibrated_sequence = FITSSequence(calibrated_files)

        stack = calibrated_sequence.integrate_sequence(
            flat=True, confirm=False)

        filter_code = stack.header['FILTER']
        ccd_temp = str(round(stack.header['CCD-TEMP']))
        date_obs = datetime.strptime(
            stack.header['DATE-OBS'], '%Y-%m-%dT%H:%M:%S.%f')
        date_string = date_obs.strftime('%Y%m%d')
        gain = str(round(stack.header['GAIN']))
        offset = str(round(stack.header['OFFSET']))
        binning = str(stack.header['XBINNING']) + \
            'x' + str(stack.header['XBINNING'])
        filename = f'master_flat_{filter_code}_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits'

        stack.meta['IMAGETYP'] = 'Master Flat'

        print(f'Writing {cfg.CALIBRATION_PATH}/{filename}...')
        stack.write(f'{cfg.CALIBRATION_PATH}/{filename}', overwrite=True)
        shutil.rmtree(f'{os.getcwd()}/calibrated/')

        return True

    def filter_masters(self, image, frame, match_conditions):
        ''' Finds the right calibration master for 'image' (specified)
            by 'frame' 

            :param image: single element from FITSSequence or CCDData
            :param frame: text value of frame type (Bias/Dark/Flat)
            :match_conditions: header conditions to test (extracted from config.py)
            :return: CCDData object if succesful, False if not
        '''

        masters = []
        matches = []
        for master in self.masters.files:
            if master['header']['FRAME'] == frame:
                masters.append(master)

        for master in masters:

            match = True
            for condition in match_conditions:
                tolerance = 0
                for card in cfg.TESTED_FITS_CARDS:
                    if card['name'] == condition:
                        tolerance = card['tolerance']
                master_header = master['header'][condition]
                image_header = image['header'][condition]

                if isinstance(image_header, str):
                    if not master_header == image_header:
                        match = False
                else:
                    if not abs(master_header - image_header) <= tolerance:
                        match = False

            if match:
                matches.append(master)

        if len(matches) > 0:
            matched_master = matches[0]['filename']
            print(f'-- Master {frame}: {matched_master}')
            return matches[0]

        else:
            print(
                f'{Fore.YELLOW}-- Could not find a suitable master {frame}.{Style.RESET_ALL}')
            return False

    def subtract_bias(self, image, bias=None, write=False):
        ''' Subtract provided master bias from FITS image. 

            :param image: single element from FITSSequence or CCDData
            :param bias: single element from FITSSequence or CCDData
            :param write: boolean, set to True to write file
            :return: CCDData object if succesful, False if not
        '''

        if write:
            filename = image['filename']

        if not bias:
            bias = self.filter_masters(image, 'Bias', cfg.BIAS_CONSTRAINTS)
            if not bias:
                print(
                    f'{Style.BRIGHT + Fore.RED}No bias substraction.{Style.RESET_ALL}')
                return False

        image = hlp.extract_ccd(image)
        bias = hlp.extract_ccd(bias)

        print(f'{Style.BRIGHT + Fore.GREEN}Bias subtraction...{Style.RESET_ALL}')
        calibrated_image = ccdp.subtract_bias(image, bias)

        if write:
            new_filename = f'b_{filename}'
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)

        calibrated_image.data = calibrated_image.data.astype('float32')
        return calibrated_image

    def subtract_dark(self, image, dark=None, write=False):
        ''' Subtract provided calibrated master dark from FITS image. 

            :param image: single element from FITSSequence or CCDData
            :param dark: single element from FITSSequence or CCDData
            :param write: boolean, set to True to write file
            :return: CCDData object if succesful, False if not
        '''

        if write:
            filename = image['filename']

        if not dark:
            dark = self.filter_masters(image, 'Dark', cfg.DARK_CONSTRAINTS)
            if not dark:
                print(
                    f'{Style.BRIGHT + Fore.RED}No dark substraction.{Style.RESET_ALL}')
                return False

        image = hlp.extract_ccd(image)
        dark = hlp.extract_ccd(dark)

        print(f'{Style.BRIGHT + Fore.GREEN}Dark subtraction...{Style.RESET_ALL}')
        calibrated_image = ccdp.subtract_dark(
            image, dark, exposure_time='EXPTIME', exposure_unit=u.second, scale=True)

        if write:
            new_filename = f'd_{filename}'
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)

        calibrated_image.data = calibrated_image.data.astype('float32')
        return calibrated_image

    def correct_flat(self, image, flat=None, write=False):
        ''' Correct FITS image with provided master flat. 

            :param image: single element from FITSSequence or CCDData
            :param flat: single element from FITSSequence or CCDData
            :param write: boolean, set to True to write file
            :return: CCDData object if succesful, False if not
        '''

        if write:
            filename = image['filename']

        if not flat:
            flat = self.filter_masters(image, 'Flat', cfg.FLAT_CONSTRAINTS)
            if not flat:
                print(
                    f'{Style.BRIGHT + Fore.RED}No flat correction.{Style.RESET_ALL}')
                return False

        image = hlp.extract_ccd(image)
        flat = hlp.extract_ccd(flat)

        print(f'{Style.BRIGHT + Fore.GREEN}Flat correction...{Style.RESET_ALL}')
        calibrated_image = ccdp.flat_correct(image, flat)

        if write:
            new_filename = f'f_{filename}'
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)

        calibrated_image.data = calibrated_image.data.astype('float32')
        return calibrated_image

    def calibrate_image(self, image, steps=None, bias=None, dark=None, flat=None, write=False):
        ''' Full calibration of FITS file. 'steps' argument allows to choose
            what calibration steps to apply.

            :param image: single element from FITSSequence or CCDData
            :param steps: python dict {bias, dark, flat: True/False}
            :param bias: single element from FITSSequence or CCDData
            :param dark: single element from FITSSequence or CCDData
            :param flat: single element from FITSSequence or CCDData
            :return: CCDData object if succesful, False if not
        '''

        if not steps:
            steps = {
                'bias': True,
                'dark': True,
                'flat': True,
            }

        calibrated_image = image
        filename = image['filename']
        new_filename = image['filename']

        print(f'\n{Style.BRIGHT}Calibrating {filename}...{Style.RESET_ALL}')
        hlp.header_summary(image)

        # Store original WCS header for preservation
        original_wcs_header = None
        original_path = image['path'] if isinstance(image, dict) and 'path' in image else None
        if hasattr(image, 'wcs') and image.wcs is not None:
            original_wcs_header = image.wcs.to_header()

        if steps['bias']:
            if not bias:
                bias = self.filter_masters(image, 'Bias', cfg.BIAS_CONSTRAINTS)
            if bias:
                calibrated_image = self.subtract_bias(calibrated_image, bias)
                new_filename = f'b_{new_filename}'

        if steps['dark']:
            if not dark:
                dark = self.filter_masters(image, 'Dark', cfg.DARK_CONSTRAINTS)
            if dark:
                calibrated_image = self.subtract_dark(calibrated_image, dark)
                new_filename = f'd_{new_filename}'

        if steps['flat']:
            if not flat:
                flat = self.filter_masters(image, 'Flat', cfg.FLAT_CONSTRAINTS)
            if flat:
                calibrated_image = self.correct_flat(calibrated_image, flat)
                new_filename = f'f_{new_filename}'

        if write and not hasattr(calibrated_image, 'write'):
            print('-- Nothing to write')
        elif write and hasattr(calibrated_image, 'write'):
            print(f'-- Writing {write_path/new_filename}...')
            calibrated_image.write(write_path / new_filename, overwrite=True)
            if original_path is not None:
                print(f'-- Restoring WCS header from {original_path}...')
                import time
                time.sleep(0.1)
                self.restore_wcs_header(original_path, write_path / new_filename)
                print(f'-- WCS header restoration completed.')

        return (calibrated_image, new_filename)

    @staticmethod
    def restore_wcs_header(original_path, calibrated_path):
        with fits.open(original_path) as orig, fits.open(calibrated_path, mode='update') as cal:
            wcs_keys = ['CTYPE1', 'CTYPE2', 'CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2', 'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2']
            copied_keys = []
            for key in wcs_keys:
                if key in orig[0].header:
                    cal[0].header[key] = orig[0].header[key]
                    copied_keys.append(key)
            removed_keys = []
            for key in ['CDELT1', 'CDELT2', 'CROTA1', 'CROTA2']:
                if key in cal[0].header:
                    del cal[0].header[key]
                    removed_keys.append(key)
            cal.flush()
