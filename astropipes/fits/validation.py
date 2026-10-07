"""
Consistency checks across a sequence of FITS files before combining them.
"""

from typing import List, Optional

import numpy as np
from astropy.io import fits
from colorama import Fore, Style

from astropipes.config import settings
from astropipes.fits.metadata import safe_float


def sequence_inconsistencies(files: List[str], card_names: Optional[List[str]] = None) -> List[str]:
    """
    Compare header cards across a sequence of FITS files.

    Checks card_names (default: every card in settings.TESTED_FITS_CARDS), using the tolerance
    configured in TESTED_FITS_CARDS for that card (0 or unlisted = values must be identical).
    Prints one line per card and returns the problems found; an empty list means consistent.
    """
    if not files:
        return ["No input files provided"]

    print(f"\n{Style.BRIGHT}Checking FITS sequence consistency ({len(files)} files)...{Style.RESET_ALL}")

    headers = []
    for file_path in files:
        try:
            headers.append(fits.getheader(file_path, ext=0))
        except Exception as e:
            problem = f"Could not read header from {file_path}: {e}"
            print(f"{Fore.YELLOW}-- {problem}{Style.RESET_ALL}")
            return [problem]

    tolerances = {card['name']: card['tolerance'] for card in settings.TESTED_FITS_CARDS}
    if card_names is None:
        card_names = list(tolerances)

    problems = []
    for card_name in card_names:
        missing = sum(1 for header in headers if card_name not in header)
        if missing:
            problems.append(f"Missing header card {card_name} in {missing} file(s)")
            print(f"{Fore.YELLOW}-- {problems[-1]}{Style.RESET_ALL}")
            continue

        values = [header[card_name] for header in headers]
        tolerance = tolerances.get(card_name, 0)
        if tolerance:
            numeric_values = [safe_float(value) for value in values]
            average = float(np.mean(numeric_values))
            max_deviation = max(abs(value - average) for value in numeric_values)
            print(f"-- {card_name} average: {average:.2f}, max deviation: {max_deviation:.2f}")
            if max_deviation > tolerance:
                problems.append(f"{card_name} values exceed tolerance: {max_deviation:.2f} > {tolerance}")
                print(f"{Fore.YELLOW}-- {problems[-1]}{Style.RESET_ALL}")
        elif len(set(values)) > 1:
            problems.append(f"Multiple {card_name} values in sequence: {set(values)}")
            print(f"{Fore.YELLOW}-- {problems[-1]}{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}-- {card_name} values are consistent: {values[0]}{Style.RESET_ALL}")

    return problems
