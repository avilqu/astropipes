import requests
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy import units as u
from astropy.wcs import WCS
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
import logging

from astroquery.simbad import Simbad

class SolarSystemObject:
    """Class to represent a solar system object found in the field"""
    def __init__(self, name: str, ra: float, dec: float, magnitude: float, 
                 object_type: str, distance: float = None, velocity: float = None):
        self.name = name
        self.ra = ra  # degrees
        self.dec = dec  # degrees
        self.magnitude = magnitude
        self.object_type = object_type
        self.distance = distance  # AU
        self.velocity = velocity  # arcsec/hour
    def __str__(self):
        return f"{self.name} ({self.object_type}) - RA: {self.ra:.4f}°, Dec: {self.dec:.4f}°, Mag: {self.magnitude:.2f}"

class SIMBADObject:
    """Class to represent a SIMBAD object found in the field"""
    def __init__(self, name: str, ra: float, dec: float, object_type: str = "Unknown", 
                 magnitude: float = None, distance: float = None, distance_unit: str = None):
        self.name = name
        self.ra = ra  # degrees
        self.dec = dec  # degrees
        self.object_type = object_type
        self.magnitude = magnitude
        self.distance = distance  # distance value
        self.distance_unit = distance_unit  # distance unit (pc, kpc, Mpc, etc.)
    def __str__(self):
        mag_str = ""
        if self.magnitude is not None:
            try:
                mag_str = f", Mag: {float(self.magnitude):.2f}"
            except (ValueError, TypeError):
                mag_str = f", Mag: {self.magnitude}"
        dist_str = ""
        if self.distance is not None:
            try:
                unit = self.distance_unit if self.distance_unit else "pc"
                dist_str = f", Dist: {float(self.distance):.1f}{unit}"
            except (ValueError, TypeError):
                unit = self.distance_unit if self.distance_unit else "pc"
                dist_str = f", Dist: {self.distance}{unit}"
        return f"{self.name} ({self.object_type}) - RA: {self.ra:.4f}°, Dec: {self.dec:.4f}°{mag_str}{dist_str}"

class GaiaObject:
    """Class to represent a Gaia star found in the field"""
    def __init__(self, source_id: str, ra: float, dec: float, magnitude: float, 
                 parallax: float = None, pm_ra: float = None, pm_dec: float = None):
        self.source_id = source_id
        self.ra = ra  # degrees
        self.dec = dec  # degrees
        self.magnitude = magnitude
        self.parallax = parallax  # mas
        self.pm_ra = pm_ra  # mas/year
        self.pm_dec = pm_dec  # mas/year
        self.name = f"Gaia {source_id}"
        
    def __str__(self):
        return f"Gaia {self.source_id} - RA: {self.ra:.4f}°, Dec: {self.dec:.4f}°, Mag: {self.magnitude:.2f}"

class AstrometryCatalog:
    """Class to handle catalog searches and astrometry operations"""
    def __init__(self):
        self.skybot_url = "http://vo.imcce.fr/webservices/skybot/skybotconesearch_query.php"
        self.simbad_url = "http://simbad.u-strasbg.fr/simbad/sim-id"
    def simbad_search(self, object_name: str) -> Optional[SIMBADObject]:
        try:
            result = Simbad.query_object(object_name)
            if result is not None:
                ra = result['ra'][0]   # already in degrees
                dec = result['dec'][0] # already in degrees
                return SIMBADObject(object_name, ra, dec, "Unknown")
            else:
                return None
        except Exception as e:
            logging.error(f"Astroquery SIMBAD error: {e}")
            return None

    def simbad_cone_search(self, ra: float, dec: float, radius: float, 
                          max_magnitude: float = 25.0) -> List[SIMBADObject]:
        """Perform a SIMBAD cone search for objects within a specified radius."""
        try:
            # Configure Simbad for cone search with object type, magnitude, and distance
            Simbad.reset_votable_fields()
            Simbad.add_votable_fields('otype', 'V', 'distance')
            
            # Deep-sky object types to include
            deep_sky_types = {
                'Cl*', 'GlC', 'OpC', 'SFR', 'HII', 'Cld', 'GNe', 'RNe', 'MoC', 'DNe', 
                'glb', 'CGb', 'HVC', 'cor', 'bub', 'SNR', 'sh', 'flt', 'LSB', 'bCG', 
                'SBG', 'H2G', 'EmG', 'AGN', 'SyG', 'Sy1', 'Sy2', 'rG', 'LIN', 'QSO', 
                'Bla', 'BLL', 'GiP', 'GiG', 'GiC', 'BiC', 'IG', 'PaG', 'GrG', 'CGG', 
                'ClG', 'PCG', 'SCG', 'PN', 'SN*'
            }
            
            # Perform the cone search
            result = Simbad.query_region(
                SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs'),
                radius=radius*u.deg
            )
            
            if result is None or len(result) == 0:
                logging.info(f"No SIMBAD objects found in cone search at RA={ra:.4f}, Dec={dec:.4f}, radius={radius:.2f}°")
                return []
            
            objects = []
            for row in result:
                try:
                    name = row['main_id'] if 'main_id' in row.colnames else str(row['matched_id'])
                    obj_ra = row['ra']  # already in degrees
                    obj_dec = row['dec']  # already in degrees
                    obj_type = row['otype'] if 'otype' in row.colnames else "Unknown"
                    
                    # Filter to only deep-sky objects
                    if obj_type not in deep_sky_types:
                        continue
                    
                    # Handle magnitude - check for masked values and NaN
                    magnitude = None
                    if 'V' in row.colnames:
                        v_val = row['V']
                        if hasattr(v_val, 'mask') and v_val.mask:
                            magnitude = None
                        elif not np.isnan(v_val):
                            magnitude = float(v_val)
                    
                    # Handle distance - check for masked values and '--'
                    distance = None
                    distance_unit = None
                    if 'mesdistance.dist' in row.colnames:
                        dist_val = row['mesdistance.dist']
                        if hasattr(dist_val, 'mask') and dist_val.mask:
                            distance = None
                        elif dist_val != '--' and not np.isnan(dist_val):
                            distance = float(dist_val)
                            # Get distance unit if available
                            if 'mesdistance.unit' in row.colnames:
                                unit_val = row['mesdistance.unit']
                                if hasattr(unit_val, 'mask') and unit_val.mask:
                                    distance_unit = None
                                elif unit_val != '--' and unit_val is not None:
                                    distance_unit = str(unit_val)
                    
                    # Filter by magnitude if specified
                    if max_magnitude < 25.0 and magnitude is not None and magnitude > max_magnitude:
                        continue
                    
                    simbad_obj = SIMBADObject(name, obj_ra, obj_dec, obj_type, magnitude, distance, distance_unit)
                    objects.append(simbad_obj)
                    logging.info(f"Found deep-sky object: {simbad_obj}")
                    
                except Exception as e:
                    logging.warning(f"Error parsing SIMBAD object: {e}")
                    continue
            
            logging.info(f"Found {len(objects)} deep-sky objects in cone search")
            return objects
            
        except Exception as e:
            logging.error(f"Error in SIMBAD cone search: {e}")
            return []

    def check_object_in_field(self, wcs: WCS, image_shape: Tuple[int, int], 
                             simbad_object: SIMBADObject) -> Tuple[bool, Optional[Tuple[float, float]]]:
        try:
            obj_coords = SkyCoord(ra=simbad_object.ra*u.deg, dec=simbad_object.dec*u.deg)
            pixel_result = wcs.world_to_pixel(obj_coords)
            if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                pixel_x, pixel_y = pixel_result
            else:
                pixel_x, pixel_y = pixel_result[0], pixel_result[1]
            if (0 <= pixel_x <= image_shape[1] and 
                0 <= pixel_y <= image_shape[0]):
                logging.info(f"Object {simbad_object.name} is in field at pixel coordinates ({pixel_x:.1f}, {pixel_y:.1f})")
                return True, (float(pixel_x), float(pixel_y))
            else:
                logging.info(f"Object {simbad_object.name} is out of field (pixel coordinates: {pixel_x:.1f}, {pixel_y:.1f})")
                return False, None
        except Exception as e:
            logging.error(f"Error checking if object {simbad_object.name} is in field: {e}")
            return False, None
    def skybot_cone_search(self, ra: float, dec: float, radius: float, 
                          epoch: Time, max_magnitude: float = 25.0) -> List[SolarSystemObject]:
        try:
            epoch_str = epoch.iso
            params = {
                'RA': ra,
                'DEC': dec,
                'SR': radius,
                'EPOCH': epoch_str,
                'LOCATION': '500',
                'MAXMAG': max_magnitude,
                'FORMAT': 'xml'
            }
            logging.info(f"Performing Skybot search at RA={ra:.4f}, Dec={dec:.4f}, radius={radius:.2f}°")
            logging.info(f"Epoch: {epoch_str}")
            response = requests.get(self.skybot_url, params=params, timeout=30)
            response.raise_for_status()
            objects = self._parse_skybot_response(response.text)
            logging.info(f"Found {len(objects)} solar system objects")
            return objects
        except requests.exceptions.RequestException as e:
            logging.error(f"Error making Skybot request: {e}")
            return []
        except Exception as e:
            logging.error(f"Error in skybot_cone_search: {e}")
            return []
    def _parse_skybot_response(self, xml_content: str) -> List[SolarSystemObject]:
        objects = []
        try:
            root = ET.fromstring(xml_content)
            error_elements = root.findall('.//error')
            if error_elements:
                for error in error_elements:
                    logging.error(f"Skybot error: {error.text}")
                return []
            tabledata = root.find('.//{http://www.ivoa.net/xml/VOTable/v1.3}TABLEDATA')
            if tabledata is None:
                logging.warning("No TABLEDATA found in Skybot response")
                return []
            rows = tabledata.findall('.//{http://www.ivoa.net/xml/VOTable/v1.3}TR')
            for row in rows:
                try:
                    cells = row.findall('.//{http://www.ivoa.net/xml/VOTable/v1.3}TD')
                    if len(cells) < 15:
                        logging.warning(f"Row has insufficient columns: {len(cells)}")
                        continue
                    num = cells[0].text.strip() if cells[0].text else ""
                    name = cells[1].text.strip() if cells[1].text else ""
                    ra_str = cells[12].text.strip() if cells[12].text else "0.0"
                    dec_str = cells[13].text.strip() if cells[13].text else "0.0"
                    try:
                        ra = float(ra_str)
                        dec = float(dec_str)
                    except ValueError:
                        logging.warning(f"Invalid coordinates for {name}: RA={ra_str}, Dec={dec_str}")
                        continue
                    obj_type = cells[4].text.strip() if cells[4].text else "Unknown"
                    mag_str = cells[5].text.strip() if cells[5].text else "99.0"
                    try:
                        magnitude = float(mag_str)
                    except ValueError:
                        magnitude = 99.0
                    dist_str = cells[9].text.strip() if cells[9].text else ""
                    try:
                        distance = float(dist_str) if dist_str else None
                    except ValueError:
                        distance = None
                    motion_ra_str = cells[7].text.strip() if cells[7].text else "0.0"
                    motion_dec_str = cells[8].text.strip() if cells[8].text else "0.0"
                    try:
                        motion_ra = float(motion_ra_str)
                        motion_dec = float(motion_dec_str)
                        velocity = np.sqrt(motion_ra**2 + motion_dec**2)
                    except ValueError:
                        velocity = None
                    if num and num != "-":
                        full_name = f"{num} {name}"
                    else:
                        full_name = name
                    sso = SolarSystemObject(full_name, ra, dec, magnitude, obj_type, distance, velocity)
                    objects.append(sso)
                    logging.info(f"Parsed object: {sso}")
                except (ValueError, AttributeError, IndexError) as e:
                    logging.warning(f"Error parsing row in Skybot response: {e}")
                    continue
        except ET.ParseError as e:
            logging.error(f"Error parsing Skybot XML response: {e}")
            return []
        return objects
    def get_field_objects(self, wcs: WCS, image_shape: Tuple[int, int], 
                         epoch: Time, radius_buffer: float = 0.1) -> List[SolarSystemObject]:
        try:
            center_x = image_shape[1] / 2
            center_y = image_shape[0] / 2
            center_coords = wcs.pixel_to_world(center_x, center_y)
            ra_center = center_coords.ra.deg
            dec_center = center_coords.dec.deg
            corners = wcs.calc_footprint()
            if corners is not None:
                max_radius = 0
                for corner_ra, corner_dec in corners:
                    dra = (corner_ra - ra_center) * np.cos(np.radians(dec_center))
                    ddec = corner_dec - dec_center
                    radius = np.sqrt(dra**2 + ddec**2)
                    max_radius = max(max_radius, radius)
                search_radius = max_radius + radius_buffer
            else:
                search_radius = 1.0 + radius_buffer
            logging.info(f"Field center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
            logging.info(f"Search radius: {search_radius:.3f}°")
            objects = self.skybot_cone_search(ra_center, dec_center, search_radius, epoch)
            filtered_objects = []
            for obj in objects:
                try:
                    obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                    pixel_result = wcs.world_to_pixel(obj_coords)
                    if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                        pixel_x, pixel_y = pixel_result
                    else:
                        pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                    if (0 <= pixel_x <= image_shape[1] and 
                        0 <= pixel_y <= image_shape[0]):
                        filtered_objects.append(obj)
                        logging.info(f"Object in field: {obj}")
                except Exception as e:
                    logging.warning(f"Error checking if object {obj.name} is in field: {e}")
                    continue
            return filtered_objects
        except Exception as e:
            logging.error(f"Error getting field objects: {e}")
            return []
    def get_object_pixel_coordinates(self, wcs: WCS, objects: List[SolarSystemObject]) -> List[Tuple[SolarSystemObject, float, float]]:
        pixel_coords = []
        for obj in objects:
            try:
                obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                pixel_result = wcs.world_to_pixel(obj_coords)
                if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                    pixel_x, pixel_y = pixel_result
                else:
                    pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                pixel_coords.append((obj, float(pixel_x), float(pixel_y)))
            except Exception as e:
                logging.warning(f"Error converting coordinates for {obj.name}: {e}")
                continue
        return pixel_coords 

    def get_field_simbad_objects(self, wcs: WCS, image_shape: Tuple[int, int], 
                                radius_buffer: float = 0.1) -> List[SIMBADObject]:
        """Get deep-sky SIMBAD objects in the field of view."""
        try:
            center_x = image_shape[1] / 2
            center_y = image_shape[0] / 2
            center_coords = wcs.pixel_to_world(center_x, center_y)
            ra_center = center_coords.ra.deg
            dec_center = center_coords.dec.deg
            
            # Calculate search radius based on image diagonal
            corners = wcs.calc_footprint()
            if corners is not None:
                max_radius = 0
                for corner_ra, corner_dec in corners:
                    dra = (corner_ra - ra_center) * np.cos(np.radians(dec_center))
                    ddec = corner_dec - dec_center
                    radius = np.sqrt(dra**2 + ddec**2)
                    max_radius = max(max_radius, radius)
                search_radius = max_radius + radius_buffer
            else:
                search_radius = 1.0 + radius_buffer
            
            logging.info(f"Deep-sky SIMBAD field center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
            logging.info(f"Deep-sky SIMBAD search radius: {search_radius:.3f}°")
            
            objects = self.simbad_cone_search(ra_center, dec_center, search_radius)
            
            # Filter objects to only those actually in the field
            filtered_objects = []
            for obj in objects:
                try:
                    obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                    pixel_result = wcs.world_to_pixel(obj_coords)
                    if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                        pixel_x, pixel_y = pixel_result
                    else:
                        pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                    if (0 <= pixel_x <= image_shape[1] and 
                        0 <= pixel_y <= image_shape[0]):
                        filtered_objects.append(obj)
                        logging.info(f"Deep-sky object in field: {obj}")
                except Exception as e:
                    logging.warning(f"Error checking if SIMBAD object {obj.name} is in field: {e}")
                    continue
            
            return filtered_objects
            
        except Exception as e:
            logging.error(f"Error getting field deep-sky objects: {e}")
            return []

    def get_simbad_object_pixel_coordinates(self, wcs: WCS, objects: List[SIMBADObject]) -> List[Tuple[SIMBADObject, float, float]]:
        """Get pixel coordinates for a list of SIMBAD objects."""
        pixel_coords = []
        for obj in objects:
            try:
                obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                pixel_result = wcs.world_to_pixel(obj_coords)
                if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                    pixel_x, pixel_y = pixel_result
                else:
                    pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                pixel_coords.append((obj, float(pixel_x), float(pixel_y)))
            except Exception as e:
                logging.warning(f"Error converting coordinates for SIMBAD object {obj.name}: {e}")
                continue
        return pixel_coords 

    def gaia_cone_search(self, ra: float, dec: float, radius: float, 
                         max_magnitude: float = 12.0, gaia_dr: str = "DR3") -> List[GaiaObject]:
        """Perform a Gaia cone search for stars within a specified radius and magnitude limit."""
        try:
            logging.info(f"Performing Gaia {gaia_dr} search at RA={ra:.4f}, Dec={dec:.4f}, radius={radius:.2f}°, max_mag={max_magnitude}")
            
            # Construct the query for Gaia DR3
            query = f"""
            SELECT source_id, ra, dec, phot_g_mean_mag, parallax, pmra, pmdec
            FROM gaiadr3.gaia_source
            WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius}))
            AND phot_g_mean_mag <= {max_magnitude}
            AND phot_g_mean_mag IS NOT NULL
            ORDER BY phot_g_mean_mag
            """
            
            # Import lazily: astroquery.gaia contacts the Gaia archive at import time
            from astroquery.gaia import GaiaClass
            gaia = GaiaClass(show_server_messages=False)

            # Execute the query
            job = gaia.launch_job_async(query)
            result = job.get_results()
            
            if result is None or len(result) == 0:
                logging.info(f"No Gaia objects found in cone search")
                return []
            
            objects = []
            for row in result:
                try:
                    source_id = str(row['source_id'])
                    obj_ra = float(row['ra'])
                    obj_dec = float(row['dec'])
                    magnitude = float(row['phot_g_mean_mag'])
                    
                    # Handle optional fields
                    parallax = None
                    if 'parallax' in row.colnames and row['parallax'] is not None:
                        parallax = float(row['parallax'])
                    
                    pm_ra = None
                    if 'pmra' in row.colnames and row['pmra'] is not None:
                        pm_ra = float(row['pmra'])
                    
                    pm_dec = None
                    if 'pmdec' in row.colnames and row['pmdec'] is not None:
                        pm_dec = float(row['pmdec'])
                    
                    gaia_obj = GaiaObject(source_id, obj_ra, obj_dec, magnitude, parallax, pm_ra, pm_dec)
                    objects.append(gaia_obj)
                    logging.info(f"Found Gaia object: {gaia_obj}")
                    
                except Exception as e:
                    logging.warning(f"Error parsing Gaia object: {e}")
                    continue
            
            logging.info(f"Found {len(objects)} Gaia objects in cone search")
            return objects
            
        except Exception as e:
            logging.error(f"Error in Gaia cone search: {e}")
            return []

    def get_field_gaia_objects(self, wcs: WCS, image_shape: Tuple[int, int], 
                              max_magnitude: float = 12.0, radius_buffer: float = 0.1) -> List[GaiaObject]:
        """Get Gaia stars in the field of view."""
        try:
            center_x = image_shape[1] / 2
            center_y = image_shape[0] / 2
            center_coords = wcs.pixel_to_world(center_x, center_y)
            ra_center = center_coords.ra.deg
            dec_center = center_coords.dec.deg
            
            # Calculate search radius based on image diagonal
            corners = wcs.calc_footprint()
            if corners is not None:
                max_radius = 0
                for corner_ra, corner_dec in corners:
                    dra = (corner_ra - ra_center) * np.cos(np.radians(dec_center))
                    ddec = corner_dec - dec_center
                    radius = np.sqrt(dra**2 + ddec**2)
                    max_radius = max(max_radius, radius)
                search_radius = max_radius + radius_buffer
            else:
                search_radius = 1.0 + radius_buffer
            
            logging.info(f"Gaia field center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
            logging.info(f"Gaia search radius: {search_radius:.3f}°")
            
            objects = self.gaia_cone_search(ra_center, dec_center, search_radius, max_magnitude)
            
            # Filter objects to only those actually in the field
            filtered_objects = []
            for obj in objects:
                try:
                    obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                    pixel_result = wcs.world_to_pixel(obj_coords)
                    if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                        pixel_x, pixel_y = pixel_result
                    else:
                        pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                    if (0 <= pixel_x <= image_shape[1] and 
                        0 <= pixel_y <= image_shape[0]):
                        filtered_objects.append(obj)
                        logging.info(f"Gaia object in field: {obj}")
                except Exception as e:
                    logging.warning(f"Error checking if Gaia object {obj.source_id} is in field: {e}")
                    continue
            
            return filtered_objects
            
        except Exception as e:
            logging.error(f"Error getting field Gaia objects: {e}")
            return []

    def get_gaia_object_pixel_coordinates(self, wcs: WCS, objects: List[GaiaObject]) -> List[Tuple[GaiaObject, float, float]]:
        """Get pixel coordinates for a list of Gaia objects."""
        pixel_coords = []
        for obj in objects:
            try:
                obj_coords = SkyCoord(ra=obj.ra*u.deg, dec=obj.dec*u.deg)
                pixel_result = wcs.world_to_pixel(obj_coords)
                if hasattr(pixel_result, '__len__') and len(pixel_result) == 2:
                    pixel_x, pixel_y = pixel_result
                else:
                    pixel_x, pixel_y = pixel_result[0], pixel_result[1]
                pixel_coords.append((obj, float(pixel_x), float(pixel_y)))
            except Exception as e:
                logging.warning(f"Error converting coordinates for Gaia object {obj.source_id}: {e}")
                continue
        return pixel_coords 