from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QInputDialog, QMessageBox
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QBrush, QColor
from lib.db import get_db_manager
from lib.db.edit import rename_target_across_database
from lib.gui.library.context_dropdown import build_sidebar_target_menu
from lib.gui.library.masters_generation_thread import MastersGenerationThread
from lib.gui.common.console_window import ConsoleOutputWindow
from config import TIME_DISPLAY_MODE, ARCHIVE_PATH

class LeftPanel(QWidget):
    menu_selection_changed = pyqtSignal(str, str)  # (category, value)
    target_renamed = pyqtSignal(str, str)  # (old_name, new_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.menu_tree = QTreeWidget()
        self.menu_tree.setHeaderHidden(True)
        self.menu_tree.setIndentation(16)
        self.menu_tree.setAnimated(True)
        self.menu_tree.setMinimumWidth(200)
        self.menu_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.menu_tree.setColumnCount(1)

        # Set up context menu for targets
        self.menu_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.menu_tree.customContextMenuRequested.connect(self._show_context_menu)

        # Set light grey text color, bigger font, and padding
        self.menu_tree.setStyleSheet("""
            QTreeWidget {
                color: #ffffff;
                font-size: 14px;
            }
    
        """)

        # Initialize database connection
        db = get_db_manager()
        
        # Top-level items
        self.obslog_item = QTreeWidgetItem(["Obs log"])
        self.targets_item = QTreeWidgetItem(["Targets"])
        self.dates_item = QTreeWidgetItem(["Dates"])
        self.menu_tree.addTopLevelItem(self.obslog_item)
        self.menu_tree.addTopLevelItem(self.targets_item)
        self.menu_tree.addTopLevelItem(self.dates_item)

        # Set bold font for expandable items
        bold_font = QFont()
        bold_font.setBold(True)
        self.targets_item.setFont(0, bold_font)
        self.obslog_item.setFont(0, bold_font)
        self.dates_item.setFont(0, bold_font)
        # Calibration section
        self.calibration_item = QTreeWidgetItem(["Calibration"])
        self.calibration_item.setFont(0, bold_font)
        bias_count = db.get_calibration_file_count("Bias")
        darks_count = db.get_calibration_file_count("Dark")
        flats_count = db.get_calibration_file_count("Flat")

        self.darker_brush = QBrush(QColor("#bbbbbb"))
        self.bias_item = QTreeWidgetItem([f"Bias ({bias_count})"])
        self.bias_item.setForeground(0, self.darker_brush)
        self.darks_item = QTreeWidgetItem([f"Darks ({darks_count})"])
        self.darks_item.setForeground(0, self.darker_brush)
        self.flats_item = QTreeWidgetItem([f"Flats ({flats_count})"])
        self.flats_item.setForeground(0, self.darker_brush)
        self.calibration_item.addChild(self.bias_item)
        self.calibration_item.addChild(self.darks_item)
        self.calibration_item.addChild(self.flats_item)
        self.menu_tree.addTopLevelItem(self.calibration_item)
        self.menu_tree.expandItem(self.calibration_item)

        # Populate targets and dates immediately
        for target in db.get_unique_targets():
            count = db.get_file_count_by_target(target)
            item = QTreeWidgetItem(self.targets_item, [f"{target} ({count})"])
            item.setForeground(0, self.darker_brush)
        if TIME_DISPLAY_MODE == 'Local':
            for date in reversed(db.get_unique_local_dates()):
                count = db.get_file_count_by_local_date(date)
                item = QTreeWidgetItem(self.dates_item, [f"{date} ({count})"])
                item.setForeground(0, self.darker_brush)
        else:
            for date in reversed(db.get_unique_dates()):
                count = db.get_file_count_by_date(date)
                item = QTreeWidgetItem(self.dates_item, [f"{date} ({count})"])
                item.setForeground(0, self.darker_brush)

        # Expand both Targets and Dates by default
        self.menu_tree.expandItem(self.targets_item)
        self.menu_tree.expandItem(self.dates_item)

        layout.addWidget(self.menu_tree)
        self.setMinimumWidth(200)

        self.menu_tree.currentItemChanged.connect(self._emit_selection)

    def _emit_selection(self, current, previous):
        if current is self.obslog_item:
            self.menu_selection_changed.emit("obslog", "")
        elif current is self.targets_item:
            self.menu_selection_changed.emit("targets", "")
        elif current is self.dates_item:
            self.menu_selection_changed.emit("dates", "")
        elif current.parent() is self.targets_item:
            # Extract target name from "Target (count)" format
            target_text = current.text(0)
            target_name = target_text.split(" (")[0]
            self.menu_selection_changed.emit("target", target_name)
        elif current.parent() is self.dates_item:
            # Extract date from "Date (count)" format
            date_text = current.text(0)
            date_name = date_text.split(" (")[0]
            self.menu_selection_changed.emit("date", date_name)
        elif current is self.darks_item:
            self.menu_selection_changed.emit("darks", "")
        elif current is self.bias_item:
            self.menu_selection_changed.emit("bias", "")
        elif current is self.flats_item:
            self.menu_selection_changed.emit("flats", "")
        else:
            self.menu_selection_changed.emit("unknown", current.text(0))

    def _show_context_menu(self, pos):
        item = self.menu_tree.itemAt(pos)
        if item and item.parent() is self.targets_item:
            # This is a target item
            target_text = item.text(0)
            target_name = target_text.split(" (")[0]
            def show_info():
                # Placeholder: show info for the target
                print(f"Show info for target: {target_name}")
            def rename_target():
                new_name, ok = QInputDialog.getText(self, "Rename Target", f"Enter new name for target '{target_name}':")
                if ok and new_name and new_name.strip() and new_name.strip() != target_name:
                    result = rename_target_across_database(target_name, new_name.strip())
                    msg = f"Updated {result['files_updated']} files."
                    
                    # Add folder renaming information
                    if result['folder_renamed']:
                        msg += f"\n\nFolder renamed successfully from '{target_name}' to '{new_name.strip()}'"
                    elif result['folder_error']:
                        msg += f"\n\nFolder rename failed: {result['folder_error']}"
                    
                    if result['errors']:
                        msg += f"\n\nFile update errors:\n" + '\n'.join(f"{e['path']}: {e['error']}" for e in result['errors'])
                    
                    QMessageBox.information(self, "Rename Target", msg)
                    self.refresh_counts()
                    self.target_renamed.emit(target_name, new_name.strip())
            def generate_masters():
                """Generate masters for the target: calibrate, align, integrate all images per filter."""
                try:
                    db = get_db_manager()
                    files = db.get_files_by_target(target_name)
                    
                    if not files:
                        QMessageBox.warning(self, "No Files", f"No files found for target '{target_name}'.")
                        return
                    
                    # Show console window
                    console_window = ConsoleOutputWindow(f"Generating Masters: {target_name}", self)
                    console_window.show_and_raise()
                    
                    # Ensure threads are kept alive
                    if not hasattr(self, '_masters_generation_threads'):
                        self._masters_generation_threads = []
                    
                    # Create masters generation thread
                    thread = MastersGenerationThread(target_name, files)
                    self._masters_generation_threads.append(thread)
                    
                    def on_output(text):
                        console_window.append_text(text)
                    
                    def on_finished(result):
                        # Remove thread from list
                        if thread in self._masters_generation_threads:
                            self._masters_generation_threads.remove(thread)
                        
                        if result.get('error'):
                            console_window.append_text(f"\n{result['error']}\n")
                            return
                        
                        if result.get('success'):
                            console_window.append_text(f"\n✓ Masters generation completed successfully!\n")
                            console_window.append_text(f"Processed {result.get('total_filters', 0)} filter(s)\n")
                            console_window.append_text(f"Successful: {result.get('successful_filters', 0)}\n")
                            console_window.append_text(f"Failed: {result.get('failed_filters', 0)}\n")
                            
                            # Show summary dialog
                            summary = f"Masters generation completed for target '{target_name}'.\n\n"
                            summary += f"Filters processed: {result.get('total_filters', 0)}\n"
                            summary += f"Successful: {result.get('successful_filters', 0)}\n"
                            summary += f"Failed: {result.get('failed_filters', 0)}\n\n"
                            
                            if result.get('results'):
                                summary += "Results:\n"
                                for filter_name, filter_result in result['results'].items():
                                    if filter_result.get('success'):
                                        summary += f"  {filter_name}: ✓ Integrated image saved\n"
                                    else:
                                        summary += f"  {filter_name}: ✗ {filter_result.get('error', 'Unknown error')}\n"
                            
                            QMessageBox.information(self, "Masters Generation Complete", summary)
                        else:
                            console_window.append_text(f"\n✗ Masters generation failed\n")
                    
                    # Connect signals
                    thread.output.connect(on_output)
                    thread.finished.connect(on_finished)
                    console_window.cancel_requested.connect(thread.stop)
                    
                    # Start generation
                    console_window.append_text(f"Starting masters generation for target: {target_name}\n")
                    console_window.append_text(f"Total files: {len(files)}\n\n")
                    thread.start()
                    
                except Exception as e:
                    QMessageBox.critical(
                        self, 
                        "Masters Generation Error", 
                        f"An error occurred while starting masters generation:\n{str(e)}"
                    )
            
            def move_to_archive():
                # Confirm the action
                reply = QMessageBox.question(
                    self, 
                    "Move to Archive", 
                    f"Are you sure you want to move all files for target '{target_name}' to the archive?\n\n"
                    f"This will move the files to {ARCHIVE_PATH} and remove them from the database.\n"
                    f"This action cannot be undone.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        db = get_db_manager()
                        result = db.move_target_to_archive(target_name, ARCHIVE_PATH)
                        
                        if result['errors']:
                            error_msg = f"Archived {result['files_moved']} files and removed {result['files_removed']} database entries.\n\n"
                            error_msg += "Errors occurred:\n" + '\n'.join(f"{e['path']}: {e['error']}" for e in result['errors'])
                            QMessageBox.warning(self, "Archive Complete with Errors", error_msg)
                        else:
                            QMessageBox.information(
                                self, 
                                "Archive Complete", 
                                f"Successfully archived {result['files_moved']} files and removed {result['files_removed']} database entries."
                            )
                        
                        # Refresh the sidebar to reflect the changes
                        self.repopulate_targets_and_dates()
                        
                    except Exception as e:
                        QMessageBox.critical(
                            self, 
                            "Archive Error", 
                            f"An error occurred while archiving the target:\n{str(e)}"
                        )
            
            menu = build_sidebar_target_menu(
                self.menu_tree, 
                target_name=target_name, 
                show_info_callback=show_info, 
                rename_target_callback=rename_target,
                move_to_archive_callback=move_to_archive,
                generate_masters_callback=generate_masters
            )
            menu.exec(self.menu_tree.viewport().mapToGlobal(pos))

    def set_menu_index(self, index):
        item = [self.obslog_item, self.targets_item, self.dates_item][index]
        self.menu_tree.setCurrentItem(item)

    def refresh_counts(self):
        """Refresh the file counts for all items in the tree."""
        db = get_db_manager()
        
        # Refresh target counts
        for i in range(self.targets_item.childCount()):
            child = self.targets_item.child(i)
            target_name = child.text(0).split(" (")[0]
            count = db.get_file_count_by_target(target_name)
            child.setText(0, f"{target_name} ({count})")
        
        # Refresh date counts
        for i in range(self.dates_item.childCount()):
            child = self.dates_item.child(i)
            date_name = child.text(0).split(" (")[0]
            if TIME_DISPLAY_MODE == 'Local':
                count = db.get_file_count_by_local_date(date_name)
            else:
                count = db.get_file_count_by_date(date_name)
            child.setText(0, f"{date_name} ({count})")
        
        # Refresh calibration counts
        bias_count = db.get_calibration_file_count("Bias")
        darks_count = db.get_calibration_file_count("Dark")
        flats_count = db.get_calibration_file_count("Flat")
        self.bias_item.setText(0, f"Bias ({bias_count})")
        self.darks_item.setText(0, f"Darks ({darks_count})")
        self.flats_item.setText(0, f"Flats ({flats_count})") 

    def repopulate_targets_and_dates(self):
        """Clear and repopulate the targets and dates lists from the database."""
        db = get_db_manager()
        # Remove all children from targets and dates
        self.targets_item.takeChildren()
        self.dates_item.takeChildren()
        # Repopulate targets
        for target in db.get_unique_targets():
            count = db.get_file_count_by_target(target)
            item = QTreeWidgetItem(self.targets_item, [f"{target} ({count})"])
            item.setForeground(0, self.darker_brush)
        # Repopulate dates
        if TIME_DISPLAY_MODE == 'Local':
            for date in reversed(db.get_unique_local_dates()):
                count = db.get_file_count_by_local_date(date)
                item = QTreeWidgetItem(self.dates_item, [f"{date} ({count})"])
                item.setForeground(0, self.darker_brush)
        else:
            for date in reversed(db.get_unique_dates()):
                count = db.get_file_count_by_date(date)
                item = QTreeWidgetItem(self.dates_item, [f"{date} ({count})"])
                item.setForeground(0, self.darker_brush)
        # Expand both Targets and Dates by default
        self.menu_tree.expandItem(self.targets_item)
        self.menu_tree.expandItem(self.dates_item) 