import numpy as np


class HistogramController:
    """
    Handles all histogram stretch and brightness adjustment functionality
    for the FITS viewer.
    """

    _PER_IMAGE_BRIGHTNESS_STEPS = 10

    def __init__(self, parent_viewer):
        self.parent = parent_viewer
        self.stretch_mode = 'linear'  # 'linear' or 'log', default to linear
        self.clipping_enabled = False
        self.display_min = None
        self.display_max = None
        self.sigma_clip = 3.0
        self.stretch_locked = True
        self.locked_display_min = None
        self.locked_display_max = None
        self.brightness_adjustment = 0.0  # DN offset from auto min, kept across frames

        self._create_ui_elements()

    def _create_ui_elements(self):
        """Create histogram-related UI elements for the toolbar."""
        tc = self.parent.toolbar_controller
        self.linear_action = tc.linear_action
        self.log_action = tc.log_action
        self.brightness_slider = tc.brightness_slider
        self.clipping_action = tc.clipping_action

    def _stretch_data(self, image_data=None):
        """Return image values in the space used for display stretch."""
        if image_data is None:
            image_data = self.parent.image_data
        if image_data is None:
            return None
        if self.stretch_mode == 'log':
            data = image_data.astype(float)
            mask = data > 0
            log_data = np.zeros_like(data)
            log_data[mask] = np.log10(data[mask])
            return log_data
        return image_data

    def _get_auto_display_minmax_for(self, image_data=None):
        """Compute default min/max for an image (current or given array)."""
        data = self._stretch_data(image_data)
        if data is None:
            return 0.0, 1.0

        if self.clipping_enabled:
            finite_vals = data[np.isfinite(data)]
            if finite_vals.size > 0:
                mean = float(np.mean(finite_vals))
                std = float(np.std(finite_vals))
                return mean - self.sigma_clip * std, mean + self.sigma_clip * std
            return float(np.min(data)), float(np.max(data))

        finite_vals = data[np.isfinite(data)]
        if finite_vals.size > 0:
            histo = np.histogram(finite_vals, 60, None, True)
            return float(histo[1][0]), float(histo[1][-1])
        return float(np.min(data)), float(np.max(data))

    def _get_auto_display_minmax(self):
        return self._get_auto_display_minmax_for(None)

    def _apply_per_image_limits(self):
        """Per-frame auto stretch with shared brightness offset when switching frames."""
        auto_min, auto_max = self._get_auto_display_minmax()
        adjusted_min = auto_min - self.brightness_adjustment
        self.display_min = adjusted_min
        self.display_max = auto_max
        self.locked_display_min = adjusted_min
        self.locked_display_max = auto_max

    def _apply_display_limits(self):
        """Recompute display_min/max and refresh the view."""
        if self.parent.image_data is None:
            return
        self._apply_per_image_limits()
        self.parent.update_image_display(keep_zoom=True)
        self.update_brightness_slider_tooltip()

    def on_brightness_slider_changed(self, value):
        """Handle brightness slider value changes."""
        if self.display_min is None or self.display_max is None:
            auto_min, auto_max = self._get_auto_display_minmax()
            self.display_min = auto_min
            self.display_max = auto_max

        step = self._get_display_min_step()
        adjustment_range = self._PER_IMAGE_BRIGHTNESS_STEPS * step
        adjustment = (value - 50) / 50.0 * adjustment_range
        self.brightness_adjustment = adjustment

        auto_min, auto_max = self._get_auto_display_minmax()
        self.display_min = auto_min - adjustment
        self.locked_display_min = self.display_min
        self.locked_display_max = auto_max
        self.parent.update_image_display(keep_zoom=True)
        self.update_brightness_slider_tooltip()

    def update_brightness_slider_tooltip(self):
        if self.display_min is not None:
            self.brightness_slider.setToolTip(
                f"Adjust image brightness (min: {self.display_min:.2f})"
            )
        else:
            self.brightness_slider.setToolTip("Adjust image brightness")

    def _get_display_min_step(self):
        data = self._stretch_data()
        if data is not None:
            finite_vals = data[np.isfinite(data)]
            if finite_vals.size > 0:
                return float(np.std(finite_vals)) * 0.4
        return 4.0

    def update_display_minmax_tooltips(self):
        self.update_brightness_slider_tooltip()

    def set_linear_stretch(self):
        self.stretch_mode = 'linear'
        self._apply_display_limits()

    def set_log_stretch(self):
        self.stretch_mode = 'log'
        self._apply_display_limits()

    def toggle_clipping(self):
        self.clipping_enabled = not self.clipping_enabled
        self.clipping_action.setChecked(self.clipping_enabled)
        self._apply_display_limits()

    def toggle_stretch_lock(self):
        pass

    def update_button_states_for_no_image(self):
        pass

    def update_button_states_for_image_loaded(self):
        pass

    def initialize_for_new_image(self, restore_view=False):
        """Initialize histogram parameters for a newly loaded image."""
        if self.parent.image_data is None:
            return

        if self.locked_display_min is None or self.locked_display_max is None:
            auto_min, auto_max = self._get_auto_display_minmax()
            self.locked_display_min = auto_min
            self.locked_display_max = auto_max
            self.display_min = auto_min
            self.display_max = auto_max
        else:
            self._apply_per_image_limits()

        if hasattr(self.parent, '_last_brightness'):
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(self.parent._last_brightness)
            self.brightness_slider.blockSignals(False)
            self.on_brightness_slider_changed(self.parent._last_brightness)
        else:
            self.brightness_slider.setValue(50)

        self.parent.update_image_display(keep_zoom=restore_view)

    def save_state_before_switch(self):
        if self.parent.image_data is not None:
            self.parent._last_brightness = self.brightness_slider.value()
        else:
            self.parent._last_brightness = 50

    def get_display_parameters(self):
        return {
            'display_min': self.display_min,
            'display_max': self.display_max,
            'clipping': self.clipping_enabled,
            'sigma_clip': self.sigma_clip,
            'stretch_mode': self.stretch_mode,
        }
