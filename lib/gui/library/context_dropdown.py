from PyQt6.QtWidgets import QMenu, QMessageBox
from PyQt6.QtGui import QAction, QFont
from colorama import Fore, Style
from lib.gui.common.console_window import ConsoleOutputWindow
from .platesolving_thread import PlatesolvingThread
from .calibration_thread import CalibrationThread

def build_single_file_menu(parent=None, show_header_callback=None, show_image_callback=None, solve_image_callback=None, calibrate_and_compare_callback=None, delete_file_callback=None):
    menu = QMenu(parent)
    show_image_action = QAction("Show in FITS viewer", menu)
    font = show_image_action.font()
    font.setBold(True)
    show_image_action.setFont(font)
    if show_image_callback:
        show_image_action.triggered.connect(show_image_callback)
    menu.addAction(show_image_action)
    
    # Add separator before calibration action
    menu.addSeparator()
    
    calibrate_action = QAction("Calibrate and compare", menu)
    if calibrate_and_compare_callback:
        calibrate_action.triggered.connect(calibrate_and_compare_callback)
    menu.addAction(calibrate_action)
    
    # Add separator before solve image action
    menu.addSeparator()
    
    solve_image_action = QAction("Platesolve image", menu)
    if solve_image_callback:
        solve_image_action.triggered.connect(solve_image_callback)
    menu.addAction(solve_image_action)
    
    show_header_action = QAction("Show header", menu)
    if show_header_callback:
        show_header_action.triggered.connect(show_header_callback)
    menu.addAction(show_header_action)
    
    # Add separator before delete action
    menu.addSeparator()
    
    # Add delete action with warning styling
    delete_action = QAction("Delete file", menu)
    delete_action.setIconText("🗑️")  # Add trash icon
    if delete_file_callback:
        delete_action.triggered.connect(delete_file_callback)
    menu.addAction(delete_action)
    
    return menu

def build_calibration_single_file_menu(parent=None, show_header_callback=None, show_image_callback=None, solve_image_callback=None):
    menu = QMenu(parent)
    show_image_action = QAction("Show in FITS viewer", menu)
    font = show_image_action.font()
    font.setBold(True)
    show_image_action.setFont(font)
    if show_image_callback:
        show_image_action.triggered.connect(show_image_callback)
    menu.addAction(show_image_action)
    
    # Add separator before solve image action
    menu.addSeparator()
    
    show_header_action = QAction("Show header", menu)
    if show_header_callback:
        show_header_action.triggered.connect(show_header_callback)
    menu.addAction(show_header_action)
    return menu

def build_multi_file_menu(parent=None, load_in_viewer_callback=None, platesolve_all_callback=None, delete_files_callback=None):
    menu = QMenu(parent)
    if load_in_viewer_callback:
        load_action = QAction("Load files in FITS viewer", menu)
        font = load_action.font()
        font.setBold(True)
        load_action.setFont(font)
        load_action.triggered.connect(load_in_viewer_callback)
        menu.addAction(load_action)
    if platesolve_all_callback:
        platesolve_action = QAction("Platesolve all images", menu)
        platesolve_action.triggered.connect(platesolve_all_callback)
        menu.addAction(platesolve_action)
    
    # Add separator before delete action if we have other actions
    if (load_in_viewer_callback or platesolve_all_callback) and delete_files_callback:
        menu.addSeparator()
    
    # Add delete action for multiple files
    if delete_files_callback:
        delete_action = QAction("Delete selected files", menu)
        delete_action.setIconText("🗑️")  # Add trash icon
        delete_action.triggered.connect(delete_files_callback)
        menu.addAction(delete_action)
    
    if not load_in_viewer_callback and not platesolve_all_callback and not delete_files_callback:
        menu.addAction("No actions available (multiple files)")
    return menu

def build_empty_menu(parent=None):
    menu = QMenu(parent)
    menu.addAction("No actions available (empty menu)")
    return menu 

def build_sidebar_target_menu(parent=None, target_name=None, show_info_callback=None, rename_target_callback=None, move_to_archive_callback=None, generate_masters_callback=None, add_to_mpc_log_callback=None, load_in_viewer_callback=None, generate_daily_stacks_callback=None):
    menu = QMenu(parent)
    
    # Add "Load all files in FITS Viewer" action at the top
    if load_in_viewer_callback:
        load_action = QAction("Load all files in FITS Viewer", menu)
        font = load_action.font()
        font.setBold(True)
        load_action.setFont(font)
        load_action.triggered.connect(load_in_viewer_callback)
        menu.addAction(load_action)
    
    # Add separator if we have top actions
    if load_in_viewer_callback:
        menu.addSeparator()
    
    # Add rename action
    rename_action = QAction("Rename target", menu)
    if rename_target_callback:
        rename_action.triggered.connect(rename_target_callback)
    menu.addAction(rename_action)
    
    # Add separator before generate masters action
    menu.addSeparator()
    
    # Add generate masters action
    generate_masters_action = QAction("Generate masters", menu)
    if generate_masters_callback:
        generate_masters_action.triggered.connect(generate_masters_callback)
    menu.addAction(generate_masters_action)
    
    # Add "Generate daily stacks" action after Generate masters
    if generate_daily_stacks_callback:
        daily_stacks_action = QAction("Generate daily stacks", menu)
        daily_stacks_action.triggered.connect(generate_daily_stacks_callback)
        menu.addAction(daily_stacks_action)
    
    # Add separator before MPC log action
    menu.addSeparator()
    
    # Add "Add to MPC log" action
    add_mpc_action = QAction("Add to MPC log", menu)
    if add_to_mpc_log_callback:
        add_mpc_action.triggered.connect(add_to_mpc_log_callback)
    menu.addAction(add_mpc_action)
    
    # Add separator before archive action
    menu.addSeparator()
    
    # Add move to archive action
    archive_action = QAction("Move to archive", menu)
    if move_to_archive_callback:
        archive_action.triggered.connect(move_to_archive_callback)
    menu.addAction(archive_action)
    
    return menu

def build_sidebar_date_menu(parent=None, date_name=None, load_in_viewer_callback=None):
    menu = QMenu(parent)
    
    # Add "Load all files in FITS Viewer" action
    if load_in_viewer_callback:
        load_action = QAction("Load all files in FITS Viewer", menu)
        font = load_action.font()
        font.setBold(True)
        load_action.setFont(font)
        load_action.triggered.connect(load_in_viewer_callback)
        menu.addAction(load_action)
    
    return menu 

def platesolve_multiple_files(parent, files, on_all_finished=None):
    """
    Platesolve a list of FITS files sequentially, showing output in a console window.
    parent: the parent widget (for dialog parenting)
    files: list of file objects (must have .path)
    on_all_finished: optional callback to call when all files are done
    """
    console_window = ConsoleOutputWindow("Platesolving All Files", parent)
    console_window.show_and_raise()
    queue = list(files)
    results = []
    cancelled = {"flag": False}
    # Ensure threads are kept alive
    if not hasattr(parent, '_platesolving_threads'):
        parent._platesolving_threads = []

    def next_in_queue():
        if cancelled["flag"]:
            console_window.append_text("\nPlatesolving cancelled by user.\n")
            if on_all_finished:
                on_all_finished(results)
            return
        if not queue:
            console_window.append_text("\nAll files platesolved.\n")
            if on_all_finished:
                on_all_finished(results)
            return
        fits_file = queue.pop(0)
        fits_path = fits_file.path
        console_window.append_text(f"\nPlatesolving: {fits_path}\n")
        thread = PlatesolvingThread(fits_path)
        parent._platesolving_threads.append(thread)
        thread.output.connect(console_window.append_text)
        thread.finished.connect(lambda result: on_finished(result))
        def on_finished(result):
            results.append(result)
            msg = parent._format_platesolving_result(result) if hasattr(parent, '_format_platesolving_result') else str(result)
            console_window.append_text(f"\n{msg}\n")
            # Remove thread from list
            if thread in parent._platesolving_threads:
                parent._platesolving_threads.remove(thread)
            next_in_queue()
        thread.start()
    
    # Connect cancel button
    console_window.cancel_requested.connect(lambda: setattr(cancelled, 'flag', True))
    
    # Start the process
    next_in_queue()

def calibrate_and_compare_file(parent, fits_file, show_image_callback=None, show_both_callback=None):
    """
    Calibrate a FITS file and then open both original and calibrated versions in the viewer.
    parent: the parent widget (for dialog parenting)
    fits_file: file object (must have .path)
    show_image_callback: callback to show single image in viewer
    show_both_callback: callback to show both images in same viewer instance
    """
    console_window = ConsoleOutputWindow("Calibrating File", parent)
    console_window.show_and_raise()
    
    # Ensure threads are kept alive
    if not hasattr(parent, '_calibration_threads'):
        parent._calibration_threads = []
    
    # Create calibration thread
    thread = CalibrationThread(fits_file.path)
    parent._calibration_threads.append(thread)
    
    def on_output(text):
        console_window.append_text(text)
    
    def on_finished(result):
        # Remove thread from list
        if thread in parent._calibration_threads:
            parent._calibration_threads.remove(thread)
        
        if 'error' in result:
            console_window.append_text(f"\n{Fore.RED}Calibration failed: {result['error']}{Style.RESET_ALL}\n")
            return
        
        if result.get('success'):
            console_window.append_text(f"\n{Fore.GREEN}Calibration completed successfully!{Style.RESET_ALL}\n")
            console_window.append_text(f"Original: {result['original_path']}\n")
            console_window.append_text(f"Calibrated: {result['calibrated_path']}\n")
            
            # Open both files in viewer if callback provided
            if show_both_callback:
                console_window.append_text(f"\nOpening both files in FITS viewer...\n")
                try:
                    # Open both files in the same viewer instance
                    show_both_callback(result['original_path'], result['calibrated_path'])
                    console_window.append_text(f"{Fore.GREEN}Both files opened in same viewer instance!{Style.RESET_ALL}\n")
                except Exception as e:
                    console_window.append_text(f"{Fore.RED}Error opening files in viewer: {e}{Style.RESET_ALL}\n")
            elif show_image_callback:
                console_window.append_text(f"\nOpening both files in separate FITS viewer instances...\n")
                try:
                    # Open original file
                    show_image_callback(result['original_path'])
                    # Open calibrated file
                    show_image_callback(result['calibrated_path'])
                    console_window.append_text(f"{Fore.GREEN}Both files opened in separate viewers!{Style.RESET_ALL}\n")
                except Exception as e:
                    console_window.append_text(f"{Fore.RED}Error opening files in viewer: {e}{Style.RESET_ALL}\n")
        else:
            console_window.append_text(f"\n{Fore.RED}Calibration failed{Style.RESET_ALL}\n")
    
    # Connect signals
    thread.output.connect(on_output)
    thread.finished.connect(on_finished)
    console_window.cancel_requested.connect(thread.stop)
    
    # Start calibration
    console_window.append_text(f"Starting calibration for: {fits_file.path}\n")
    thread.start() 

def delete_files_with_confirmation(parent, fits_files, on_deletion_complete=None):
    """
    Delete FITS files with confirmation dialog.
    
    Args:
        parent: Parent widget for dialog parenting
        fits_files: List of FITS file objects to delete
        on_deletion_complete: Optional callback to call when deletion is complete
    """
    if not fits_files:
        return
    
    # Prepare confirmation message
    if len(fits_files) == 1:
        file_info = fits_files[0]
        import os
        filename = os.path.basename(file_info.path)
        target = file_info.target or "Unknown target"
        msg = f"Are you sure you want to delete this file?\n\n"
        msg += f"File: {filename}\n"
        msg += f"Target: {target}\n"
        msg += f"Path: {file_info.path}\n\n"
        msg += "This action will:\n"
        msg += "• Remove the file from the database\n"
        msg += "• Delete the physical file from disk\n\n"
        msg += "This action cannot be undone!"
    else:
        msg = f"Are you sure you want to delete {len(fits_files)} files?\n\n"
        msg += "This action will:\n"
        msg += "• Remove all files from the database\n"
        msg += "• Delete all physical files from disk\n\n"
        msg += "This action cannot be undone!"
    
    # Show confirmation dialog
    reply = QMessageBox.question(
        parent, 
        "Confirm File Deletion", 
        msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No  # Default to No for safety
    )
    
    if reply != QMessageBox.StandardButton.Yes:
        return
    
    # Proceed with deletion
    deleted_count = 0
    errors = []
    
    try:
        from .db_access import DatabaseManager
        db_manager = DatabaseManager()
        
        for fits_file in fits_files:
            try:
                # Safety check: ensure it's a FITS file
                if not fits_file.path.lower().endswith(('.fits', '.fit')):
                    errors.append(f"Not a FITS file: {fits_file.path}")
                    continue
                
                # Delete from database first
                success = db_manager.delete_fits_file(fits_file.id)
                if success:
                    # Now delete physical file
                    import os
                    if os.path.exists(fits_file.path):
                        os.remove(fits_file.path)
                        deleted_count += 1
                    else:
                        # File doesn't exist on disk, but was removed from DB
                        deleted_count += 1
                        errors.append(f"File not found on disk: {fits_file.path}")
                else:
                    errors.append(f"Failed to delete from database: {fits_file.path}")
            except Exception as e:
                errors.append(f"Error deleting {fits_file.path}: {str(e)}")
        
        # Show results
        if errors:
            error_msg = f"Deletion completed with {len(errors)} errors:\n\n"
            error_msg += "\n".join(errors[:5])  # Show first 5 errors
            if len(errors) > 5:
                error_msg += f"\n... and {len(errors) - 5} more errors"
            QMessageBox.warning(parent, "Deletion Completed with Errors", error_msg)
        else:
            QMessageBox.information(parent, "Deletion Complete", f"Successfully deleted {deleted_count} file(s).")
        
        # Call completion callback if provided
        if on_deletion_complete:
            on_deletion_complete()
            
    except Exception as e:
        QMessageBox.critical(parent, "Deletion Error", f"An error occurred during deletion: {str(e)}") 