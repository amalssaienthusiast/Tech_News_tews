import sys
from PyQt6.QtWidgets import QApplication
from gui_qt.widgets.custom_sources_manager import CustomSourcesManager
app = QApplication(sys.argv)
csm = CustomSourcesManager()
print("CustomSourcesManager loaded successfully!")
