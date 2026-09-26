''' FITSSequence class definition (data check, registration, integration).
    @author: Adrien Vilquin Barrajon <avilqu@gmail.com>
'''

from pathlib import Path
import sys
import os

from colorama import Fore, Style
import numpy as np
from astropy.io import fits
from astropy.stats import mad_std
import ccdproc as ccdp

import config as cfg
import lib.legacy.helpers as hlp


class FITSSequence:

    def __init__(self, data):
        if len(data) == 0:
            print(f'{Style.BRIGHT + Fore.RED}No input files!{Style.RESET_ALL}')
            sys.exit()

        self.files = []
        self.data = []
        self.filenames = []

        for filename in data:
            self.files.append({
                'filename': os.path.basename(filename),
                'header': fits.getheader(filename, ext=0),
                'path': filename
            })
            self.data.append(fits.getdata(filename, ext=0))
            self.filenames.append(filename)

    def check_array_consistency(self, array, name, tolerance=0):
        ''' Checks how many distinct values in an array and issues a warning if more than 1

            :param array: the array to check
            :param name: the header card name (eg: 'CCD-TEMP')
            :return: True if array is consistent
        '''

        values = []
        res = True

        for value in array:
            if len(values) == 0:
                values.append(value)
            if value not in values:
                values.append(value)

        if not tolerance:
            if len(values) > 1:
                res = False
                print(
                    f'{Fore.YELLOW}-- There are multiple {name} values in the sequence: {Style.RESET_ALL}', values)
            else:
                print(
                    f'{Fore.GREEN}-- {name} values are consistent: {Style.RESET_ALL}', values)

        else:
            average = sum(array, 0.0) / len(array)
            max_deviation = max(abs(el - average) for el in array)
            print(f'-- {name} average: ', round(average, 2))
            print(f'-- {name} max deviation: ', round(max_deviation, 2))
            if max_deviation < tolerance:
                res = True
                print(
                    f'{Fore.GREEN}-- {name} values are consistent.{Style.RESET_ALL}')
            else:
                print(
                    f'{Fore.YELLOW}-- There are multiple {name} values in the sequence: {Style.RESET_ALL}', values)

        return res

    def check_sequence_consistency(self):
        ''' Procedes to various checks over several header cards to
            test for the sanity of the FITS collection before integration

            :return: True if no warning
        '''

        tested_cards = cfg.TESTED_FITS_CARDS
        res = True

        print(
            f'\n{Style.BRIGHT}Checking FITS sequence consistency...{Style.RESET_ALL}')
        for card in tested_cards:
            card['values'] = []
            for file in self.files:
                card['values'].append(file['header'][card['name']])
            if not self.check_array_consistency(card['values'], card['name'], card['tolerance']):
                res = False

        if res:
            print(
                f'{Style.BRIGHT + Fore.GREEN}Consistent FITS sequence.{Style.RESET_ALL}')
        else:
            print(
                f'{Style.BRIGHT + Fore.RED}Inconsistent FITS sequence!{Style.RESET_ALL}')
            hlp.prompt()

        return res

    def integrate_sequence(self, flat=False, confirm=True, write=False):
        ''' Integrates self sequence with the average method and pixel
            rejection (sigma clipping), configurable in ./config.py

            :param sequence: FITSSequence object
            :param flat: if True, uses inverse median as scale - use for master flats
            :confirm: set to False to skip confirmation prompt
            :return: CCDData object
        '''

        print(
            f'\n{Style.BRIGHT}Integrating {len(self.filenames)} files...{Style.RESET_ALL}')
        if confirm:
            hlp.prompt()

        scale = None
        if flat:
            def inv_median(a):
                return 1 / np.median(a)
            scale = inv_median

        stack = ccdp.combine(
            self.filenames,
            method='average',
            scale=scale,
            sigma_clip=True,
            sigma_clip_low_thresh=cfg.SIGMA_LOW,
            sigma_clip_high_thresh=cfg.SIGMA_HIGH,
            sigma_clip_func=np.ma.median,
            sigma_clip_dev_func=mad_std,
            mem_limit=600e7,
            unit='adu',
            dtype='float32',
        )

        stack.meta['COMBINED'] = True
        stack.uncertainty = None
        stack.mask = None
        stack.flags = None

        if write:
            filter_code = stack.header['FILTER']
            filename = f'master_{filter_code}.fits'
            print(f'-- Writing {filename}...')
            stack.write(filename, overwrite=True)

        return stack

    def register_sequence(self, reference, confirm=True):
        ''' Registers self sequence against reference file and write files
            in new directory.

            :param reference: string (filename)
            :confirm: set to False to skip confirmation prompt
            :return: True if successful
        '''

        print(
            f'\n{Style.BRIGHT}Registering {len(self.filenames)} files.{Style.RESET_ALL}')
        print(f'-- Reference frame: {reference}')
        if confirm:
            hlp.prompt()

        write_path = Path(f'{os.getcwd()}/registered')
        write_path.mkdir(exist_ok=True)

        target_wcs = ccdp.CCDData.read(reference).wcs

        count = 1
        for image in self.files:
            filename = image['filename']
            print(
                f'{Style.BRIGHT}[{count}/{len(self.filenames)}]{Style.RESET_ALL} Computing for {filename}...')
            registered_image = ccdp.wcs_project(
                hlp.extract_ccd(image), target_wcs)
            registered_image.data = registered_image.data.astype('float32')
            registered_image.write(
                write_path / f'r_{filename}', overwrite=True)
            count += 1
