#!/usr/bin/env python3
"""Region detail: session stacks in field and generated PNG views."""

import os
import subprocess
import sys
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenu,
    QSplitter,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction

from lib.fits.region_views import SkyRegion, region_in_image_field
from lib.gui.library.main_table import (
    launch_viewer,
    configure_fits_table_widget,
    add_fits_file_to_table_row,
    apply_fits_table_striping,
)
from lib.gui.library.context_dropdown import build_multi_file_menu
from config import to_display_time
from lib.db import get_db_manager


class RegionDetailWidget(QWidget):
    """Session stacks and PNG views for a selected region of interest."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._title = QLabel("Select a region")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        self._title.setFont(title_font)
        layout.addWidget(self._title)

        self._stacks_label = QLabel("Stacks in field")
        self._stacks_label.setFont(title_font)
        self.stacks_table = QTableWidget()
        configure_fits_table_widget(self.stacks_table, show_stack_count_column=True)
        self.stacks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.stacks_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.stacks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stacks_table.setSortingEnabled(True)
        self.stacks_table.setShowGrid(True)
        self.stacks_table.setGridStyle(Qt.PenStyle.SolidLine)
        self.stacks_table.verticalHeader().setVisible(True)
        self.stacks_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.stacks_table.customContextMenuRequested.connect(self._stacks_context_menu)
        self.stacks_table.cellDoubleClicked.connect(self._on_stacks_double_click)

        self._views_label = QLabel("Generated views")
        self._views_label.setFont(title_font)
        self.views_table = self._make_table(
            ["PNG file", "Date obs", "Stack FITS"],
            column_widths=[420, 140, 300],
        )
        self.views_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.views_table.customContextMenuRequested.connect(self._views_context_menu)
        self.views_table.cellDoubleClicked.connect(self._on_views_double_click)

        stacks_panel = QWidget()
        stacks_layout = QVBoxLayout(stacks_panel)
        stacks_layout.setContentsMargins(0, 0, 0, 0)
        stacks_layout.setSpacing(4)
        stacks_layout.addWidget(self._stacks_label)
        stacks_layout.addWidget(self.stacks_table)

        views_panel = QWidget()
        views_layout = QVBoxLayout(views_panel)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.setSpacing(4)
        views_layout.addWidget(self._views_label)
        views_layout.addWidget(self.views_table)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(stacks_panel)
        splitter.addWidget(views_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 240])
        layout.addWidget(splitter, stretch=1)

        self._region = None
        self._view_rows = []
        self._stack_files = []

    def _make_table(self, headers=None, column_widths=None):
        t = QTableWidget()
        if headers is None:
            headers = ["Filename", "Date obs", "Target", "Filter"]
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(True)
        h = t.horizontalHeader()
        for i in range(len(headers)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        if column_widths:
            for i, width in enumerate(column_widths):
                if i < len(headers):
                    t.setColumnWidth(i, width)
        else:
            t.setColumnWidth(0, 280)
        return t

    def populate(self, region, stack_files) -> int:
        """
        Fill tables for a region.

        stack_files: session stacks only (caller filters with is_session_stack_fits_file).
        Returns the number of session stacks that contain this region.
        """
        self._region = region
        if region is None:
            self._title.setText("Select a region")
            self._stack_files = []
            self.stacks_table.setRowCount(0)
            self.views_table.setRowCount(0)
            return 0

        self._title.setText(f"{region.name} — {region.target}")
        sky = SkyRegion(
            ra_min=region.ra_min,
            ra_max=region.ra_max,
            dec_min=region.dec_min,
            dec_max=region.dec_max,
        )

        stacks = []
        for f in stack_files:
            path = getattr(f, "path", None)
            if not path or not os.path.isfile(path):
                continue
            if region_in_image_field(path, sky):
                stacks.append(f)

        stacks.sort(key=lambda x: x.date_obs or "", reverse=True)
        self._populate_stacks_table(stacks)

        views = get_db_manager().get_region_views(region.id)
        self._populate_views_table(views)
        return len(stacks)

    def _populate_stacks_table(self, stacks):
        self._stack_files = list(stacks)
        self.stacks_table.blockSignals(True)
        self.stacks_table.setRowCount(len(stacks))
        self.stacks_table.verticalHeader().setDefaultSectionSize(30)
        for row, fits_file in enumerate(stacks):
            add_fits_file_to_table_row(self.stacks_table, row, fits_file)
        self.stacks_table.setVerticalHeaderLabels([str(i + 1) for i in range(len(stacks))])
        apply_fits_table_striping(self.stacks_table)
        self.stacks_table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self.stacks_table.blockSignals(False)

    def _populate_views_table(self, views):
        self._view_rows = views
        self.views_table.setRowCount(len(views))
        for row, v in enumerate(views):
            name = os.path.basename(v.png_path)
            dt = ""
            if v.date_obs:
                dt = to_display_time(v.date_obs).strftime("%Y-%m-%d %H:%M:%S")
            stack_name = os.path.basename(v.stack_fits_path)
            for col, text in enumerate([name, dt, stack_name]):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, v.png_path)
                self.views_table.setItem(row, col, item)

    def _delete_view_at_row(self, row: int):
        if row < 0 or row >= len(self._view_rows) or self._region is None:
            return
        view = self._view_rows[row]
        png_name = os.path.basename(view.png_path)
        reply = QMessageBox.question(
            self,
            "Delete view",
            f"Delete generated view '{png_name}'?\n\n"
            "This removes the PNG file and its database entry.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        png = view.png_path
        if png and os.path.isfile(png):
            try:
                os.remove(png)
            except OSError:
                QMessageBox.warning(
                    self,
                    "Delete view",
                    f"Could not delete file:\n{png}",
                )
                return
        db = get_db_manager()
        if not db.delete_region_view(view.id):
            QMessageBox.warning(self, "Delete view", "View could not be removed from the database.")
            return
        self._populate_views_table(db.get_region_views(self._region.id))

    def _stack_path_at_row(self, row: int):
        if row < 0:
            return None
        item = self.stacks_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _selected_stack_paths(self) -> list:
        rows = sorted({idx.row() for idx in self.stacks_table.selectedIndexes()})
        paths = []
        for row in rows:
            path = self._stack_path_at_row(row)
            if path and os.path.isfile(path) and path not in paths:
                paths.append(path)
        return paths

    def _open_stacks_in_viewer(self, fits_paths: list):
        if not fits_paths:
            return
        by_path = {f.path: f for f in self._stack_files}
        sorted_paths = sorted(
            fits_paths,
            key=lambda p: getattr(by_path.get(p), "date_obs", None) or "",
        )
        launch_viewer(sorted_paths)

    def _on_stacks_double_click(self, row, _column):
        paths = self._selected_stack_paths()
        if len(paths) > 1:
            self._open_stacks_in_viewer(paths)
        else:
            path = self._stack_path_at_row(row)
            if path:
                self._open_stacks_in_viewer([path])

    def _stacks_context_menu(self, pos):
        paths = self._selected_stack_paths()
        if not paths:
            row = self.stacks_table.rowAt(pos.y())
            path = self._stack_path_at_row(row)
            if path:
                paths = [path]
        if not paths:
            return
        if len(paths) == 1:
            menu = QMenu(self)
            show_action = QAction("Show in FITS viewer", menu)
            font = show_action.font()
            font.setBold(True)
            show_action.setFont(font)
            show_action.triggered.connect(lambda: self._open_stacks_in_viewer(paths))
            menu.addAction(show_action)
        else:
            menu = build_multi_file_menu(
                self,
                load_in_viewer_callback=lambda: self._open_stacks_in_viewer(paths),
            )
        menu.exec(self.stacks_table.viewport().mapToGlobal(pos))

    def _png_path_at_views_row(self, row: int):
        if row < 0 or row >= len(self._view_rows):
            return None
        return self._view_rows[row].png_path

    def _on_views_double_click(self, row, _column):
        png_path = self._png_path_at_views_row(row)
        if png_path:
            self._open_file(png_path)

    def _views_context_menu(self, pos):
        row = self.views_table.rowAt(pos.y())
        png_path = self._png_path_at_views_row(row)
        if not png_path:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open PNG")
        open_action.triggered.connect(lambda: self._open_file(png_path))
        show_stack = menu.addAction("Show stack in FITS viewer")
        show_stack.triggered.connect(
            lambda: launch_viewer([self._view_rows[row].stack_fits_path])
        )
        menu.addSeparator()
        delete_action = menu.addAction("Delete view…")
        delete_action.triggered.connect(lambda: self._delete_view_at_row(row))
        menu.exec(self.views_table.viewport().mapToGlobal(pos))

    def _open_file(self, path):
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["start", path], shell=True)
        except Exception:
            pass
