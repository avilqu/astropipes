"""Define and persist regions of interest from the FITS viewer."""

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from lib.db import get_db_manager
from lib.db.scan import normalize_object_name
from lib.fits.region_views import SkyRegion, target_from_fits_path


class RegionOfInterestMixin:
    """Save sky regions drawn on platesolved images."""

    def on_define_roi_toggled(self, checked):
        has_wcs = self.wcs is not None
        if has_wcs and hasattr(self.wcs, "has_celestial"):
            has_wcs = self.wcs.has_celestial
        if checked and not has_wcs:
            QMessageBox.warning(
                self,
                "No WCS",
                "Platesolve this image before defining a region of interest.",
            )
            if hasattr(self, "define_roi_action"):
                self.define_roi_action.setChecked(False)
            return
        if checked and getattr(self, "zoom_region_action", None):
            self.zoom_region_action.blockSignals(True)
            self.zoom_region_action.setChecked(False)
            self.zoom_region_action.blockSignals(False)
            self.on_zoom_region_toggled(False)
        self._define_roi_mode = checked
        self.image_label.set_define_roi_mode(checked)
        if not checked:
            self.image_label.clear_define_roi_rect()

    def on_roi_region_selected(self, img_x0, img_y0, img_x1, img_y1):
        width = abs(img_x1 - img_x0)
        height = abs(img_y1 - img_y0)
        if width < 5 or height < 5:
            QMessageBox.information(self, "Region too small", "Draw a larger rectangle.")
            if hasattr(self, "define_roi_action"):
                self.define_roi_action.setChecked(False)
            return
        try:
            sky = SkyRegion.from_pixel_rect(self.wcs, img_x0, img_y0, img_x1, img_y1)
        except Exception as e:
            QMessageBox.critical(self, "WCS error", f"Could not convert region to sky coordinates:\n{e}")
            if hasattr(self, "define_roi_action"):
                self.define_roi_action.setChecked(False)
            return

        name, ok = QInputDialog.getText(
            self,
            "Region of interest",
            "Name for this region:",
        )
        if not ok or not name.strip():
            if hasattr(self, "define_roi_action"):
                self.define_roi_action.setChecked(False)
            return

        target = target_from_fits_path(self.loaded_files[self.current_file_index])
        if not target and hasattr(self, "_current_header"):
            import json
            try:
                h = self._current_header
                if isinstance(h, str):
                    h = json.loads(h)
                obj = h.get("OBJECT")
                if isinstance(obj, tuple):
                    obj = obj[0]
                if obj:
                    target = normalize_object_name(str(obj))
            except Exception:
                pass
        if not target:
            target, ok2 = QInputDialog.getText(
                self,
                "Target",
                "Target name for this region:",
            )
            if not ok2 or not target.strip():
                if hasattr(self, "define_roi_action"):
                    self.define_roi_action.setChecked(False)
                return
            target = normalize_object_name(target.strip())

        fits_path = self.loaded_files[self.current_file_index]
        try:
            db = get_db_manager()
            db.add_region_of_interest(
                name=name.strip(),
                target=target,
                ra_min=sky.ra_min,
                ra_max=sky.ra_max,
                dec_min=sky.dec_min,
                dec_max=sky.dec_max,
                defined_from_path=fits_path,
            )
            QMessageBox.information(
                self,
                "Region saved",
                f"Region '{name.strip()}' saved for target '{target}'.",
            )
        except Exception as e:
            err = str(e)
            if "uq_region_target_name" in err or "UNIQUE" in err.upper():
                QMessageBox.warning(
                    self,
                    "Duplicate name",
                    f"A region named '{name.strip()}' already exists for target '{target}'.",
                )
            else:
                QMessageBox.critical(self, "Save failed", err)
        if hasattr(self, "define_roi_action"):
            self.define_roi_action.setChecked(False)
