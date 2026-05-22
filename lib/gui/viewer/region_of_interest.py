"""Define and persist regions of interest from the FITS viewer."""

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from lib.db import get_db_manager
from lib.db.scan import normalize_object_name
from lib.fits.region_views import (
    SkyRegion,
    pixel_bbox_for_region,
    region_in_image_field,
    target_from_fits_path,
)


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

    def show_regions_in_field(self):
        """Show database regions of interest that overlap the current image field."""
        has_wcs = self.wcs is not None
        if has_wcs and hasattr(self.wcs, "has_celestial"):
            has_wcs = self.wcs.has_celestial
        if not has_wcs:
            QMessageBox.warning(
                self,
                "No WCS",
                "Platesolve this image before showing regions in the field.",
            )
            return
        if not self.loaded_files or self.current_file_index < 0:
            return
        if self.image_data is None:
            return

        self._roi_field_overlay_active = True
        items = self._compute_roi_field_overlay_items()
        if not items:
            self._roi_field_overlay = None
            self._roi_field_overlay_active = False
            QMessageBox.information(
                self,
                "No regions",
                "No saved regions of interest overlap this image field.",
            )
            if hasattr(self, "overlay_toolbar_controller"):
                self.overlay_toolbar_controller.update_overlay_button_visibility()
            self.image_label.update()
            return

        self._roi_field_overlay = items
        if hasattr(self, "overlay_toolbar_controller"):
            self.overlay_toolbar_controller._roi_field_visible = True
            self.overlay_toolbar_controller.roi_field_toggle_action.setChecked(True)
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.image_label.update()

    def refresh_roi_field_overlay(self):
        """Recompute field ROI overlay after switching images (if active)."""
        if not getattr(self, "_roi_field_overlay_active", False):
            return
        if self.image_data is None or self.wcs is None:
            self._roi_field_overlay = None
            if hasattr(self, "overlay_toolbar_controller"):
                self.overlay_toolbar_controller.update_overlay_button_visibility()
            self.image_label.update()
            return
        has_wcs = getattr(self.wcs, "has_celestial", True)
        if not has_wcs:
            self._roi_field_overlay = None
            if hasattr(self, "overlay_toolbar_controller"):
                self.overlay_toolbar_controller.update_overlay_button_visibility()
            self.image_label.update()
            return
        items = self._compute_roi_field_overlay_items()
        self._roi_field_overlay = items if items else None
        if hasattr(self, "overlay_toolbar_controller"):
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.image_label.update()

    def _compute_roi_field_overlay_items(self):
        """Return list of (region_name, (x0, y0, x1, y1)) in image pixel coordinates."""
        fits_path = self.loaded_files[self.current_file_index]
        shape = self.image_data.shape
        db = get_db_manager()
        items = []
        for region in db.get_all_regions():
            sky = SkyRegion(
                ra_min=region.ra_min,
                ra_max=region.ra_max,
                dec_min=region.dec_min,
                dec_max=region.dec_max,
            )
            if not region_in_image_field(fits_path, sky):
                continue
            bbox = pixel_bbox_for_region(self.wcs, sky, shape)
            if bbox is None:
                continue
            items.append((region.name, bbox))
        return items

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
