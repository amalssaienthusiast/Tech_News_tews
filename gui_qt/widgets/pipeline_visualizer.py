"""
Pipeline Visualizer Widget
Shows pipeline stages with visual progress indicators

Features:
- Shows 6 pipeline stages horizontally
- Visual progress indicators for each stage
- Color coding for active/completed stages
- Stage names: Discovery → Fetch → Process → Score → Filter → Display
"""

from typing import Dict, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QWidget, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QLinearGradient, QPen, QBrush

from ..theme import COLORS, Fonts


class PipelineStage(Enum):
    """Pipeline stage enumeration"""
    DISCOVERY = "Discovery"
    FETCH = "Fetch"
    PROCESS = "Process"
    SCORE = "Score"
    FILTER = "Filter"
    DISPLAY = "Display"


@dataclass
class StageState:
    """State of a pipeline stage"""
    stage: PipelineStage
    status: str  # 'idle', 'active', 'completed', 'error'
    progress: int  # 0-100
    item_count: int = 0
    message: str = ""


class StageConnector(QFrame):
    """Connector line between stages"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._completed = False
        self.setFixedSize(30, 4)
        self._update_style()
    
    def set_active(self, active: bool):
        self._active = active
        self._update_style()
    
    def set_completed(self, completed: bool):
        self._completed = completed
        self._update_style()
    
    def _update_style(self):
        if self._completed:
            color = COLORS.green
        elif self._active:
            color = COLORS.cyan
        else:
            color = COLORS.terminal_black
        
        self.setStyleSheet(f"""
            background-color: {color};
            border-radius: 2px;
        """)


class PipelineStageWidget(QFrame):
    """Single pipeline stage widget"""
    
    clicked = pyqtSignal(PipelineStage)
    
    STAGE_ICONS = {
        PipelineStage.DISCOVERY: "🔍",
        PipelineStage.FETCH: "📥",
        PipelineStage.PROCESS: "⚙",
        PipelineStage.SCORE: "📊",
        PipelineStage.FILTER: "🔖",
        PipelineStage.DISPLAY: "📱",
    }
    
    def __init__(self, stage: PipelineStage, parent=None):
        super().__init__(parent)
        self._stage = stage
        self._state = StageState(stage, 'idle', 0)
        self._pulse_animation = None
        
        self.setFixedSize(100, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """Build the stage widget"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Icon
        self.icon_label = QLabel(self.STAGE_ICONS.get(self._stage, "⚡"))
        self.icon_label.setFont(Fonts.get_qfont('lg'))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        
        # Stage name
        self.name_label = QLabel(self._stage.value)
        self.name_label.setFont(Fonts.get_qfont('xs', 'bold'))
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status/count label
        self.status_label = QLabel("Waiting...")
        self.status_label.setFont(Fonts.get_qfont('xs'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
    
    def _apply_styles(self):
        """Apply styles based on state"""
        status = self._state.status
        
        if status == 'completed':
            border_color = COLORS.green
            bg_color = COLORS.bg_visual
            icon_color = COLORS.green
        elif status == 'active':
            border_color = COLORS.cyan
            bg_color = COLORS.bg_highlight
            icon_color = COLORS.cyan
        elif status == 'error':
            border_color = COLORS.red
            bg_color = COLORS.bg_visual
            icon_color = COLORS.red
        else:  # idle
            border_color = COLORS.terminal_black
            bg_color = COLORS.bg_dark
            icon_color = COLORS.comment
        
        self.setStyleSheet(f"""
            PipelineStageWidget {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 8px;
            }}
            PipelineStageWidget:hover {{
                border: 2px solid {COLORS.blue};
            }}
        """)
        
        self.icon_label.setStyleSheet(f"color: {icon_color};")
        self.name_label.setStyleSheet(f"color: {COLORS.fg};")
        self.status_label.setStyleSheet(f"color: {icon_color};")
        
        # Progress bar style
        progress_color = icon_color
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {progress_color};
                border-radius: 2px;
            }}
        """)
    
    def set_state(self, state: StageState):
        """Update stage state"""
        self._state = state
        self.progress_bar.setValue(state.progress)
        
        # Update status text
        if state.status == 'completed':
            self.status_label.setText(f"✓ {state.item_count} items")
        elif state.status == 'active':
            self.status_label.setText(f"⚡ {state.progress}%")
        elif state.status == 'error':
            self.status_label.setText("✗ Error")
        else:
            self.status_label.setText("Waiting...")
        
        self._apply_styles()
        
        # Start pulse animation if active
        if state.status == 'active':
            self._start_pulse()
        else:
            self._stop_pulse()
    
    def _start_pulse(self):
        """Start pulse animation for active state"""
        if not self._pulse_animation:
            self._pulse_animation = QPropertyAnimation(self, b"geometry")
            self._pulse_animation.setDuration(1000)
            self._pulse_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        
        # Subtle scale effect
        self._pulse_animation.start()
    
    def _stop_pulse(self):
        """Stop pulse animation"""
        if self._pulse_animation:
            self._pulse_animation.stop()
    
    def get_stage(self) -> PipelineStage:
        return self._stage
    
    def get_state(self) -> StageState:
        return self._state
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._stage)
        super().mousePressEvent(event)


class PipelineVisualizer(QFrame):
    """
    Pipeline visualizer widget
    
    Signals:
        stage_clicked(PipelineStage): Emitted when a stage is clicked
    """
    
    stage_clicked = pyqtSignal(PipelineStage)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: Dict[PipelineStage, PipelineStageWidget] = {}
        self._connectors: List[StageConnector] = []
        self._stage_order = list(PipelineStage)
        
        self.setObjectName("cardFrame")
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._setup_ui()
        self._apply_styles()
        
        # Demo mode timer
        self._demo_stage_idx = 0
        self._demo_progress = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._simulate_pipeline)
        # self._timer.start(500)  # Update every 500ms  # DEMO TIMER DISABLED BY OPENCODE
    
    def _setup_ui(self):
        """Build the pipeline UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("⚙ Pipeline Visualizer")
        title.setObjectName("headerLabel")
        title.setFont(Fonts.get_qfont('md', 'bold'))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Throughput indicator
        self.throughput_label = QLabel("🚀 0 items/sec")
        self.throughput_label.setFont(Fonts.get_qfont('sm'))
        self.throughput_label.setStyleSheet(f"color: {COLORS.green};")
        header_layout.addWidget(self.throughput_label)
        
        layout.addLayout(header_layout)
        
        # Stages container
        stages_container = QFrame()
        stages_container.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
        
        stages_layout = QHBoxLayout(stages_container)
        stages_layout.setContentsMargins(16, 20, 16, 20)
        stages_layout.setSpacing(0)
        stages_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Create stages with connectors
        for i, stage in enumerate(self._stage_order):
            # Create stage widget
            stage_widget = PipelineStageWidget(stage, self)
            stage_widget.clicked.connect(self.stage_clicked.emit)
            self._stages[stage] = stage_widget
            stages_layout.addWidget(stage_widget)
            
            # Add connector (except for last stage)
            if i < len(self._stage_order) - 1:
                connector = StageConnector(self)
                self._connectors.append(connector)
                stages_layout.addWidget(connector)
        
        layout.addWidget(stages_container)
        
        # Footer with legend
        footer_layout = QHBoxLayout()
        footer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        legend_items = [
            (COLORS.terminal_black, "⏸ Idle"),
            (COLORS.cyan, "⚡ Active"),
            (COLORS.green, "✓ Completed"),
            (COLORS.red, "✗ Error"),
        ]
        
        for color, text in legend_items:
            legend_item = QLabel(text)
            legend_item.setFont(Fonts.get_qfont('xs'))
            legend_item.setStyleSheet(f"""
                color: {color};
                padding: 2px 8px;
                margin: 0 4px;
            """)
            footer_layout.addWidget(legend_item)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """Apply widget styles"""
        self.setStyleSheet(f"""
            PipelineVisualizer {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
    
    def set_stage_state(self, stage: PipelineStage, state: StageState):
        """Set state for a specific stage"""
        if stage in self._stages:
            self._stages[stage].set_state(state)
            self._update_connectors()
    
    def _update_connectors(self):
        """Update connector states based on stage progress"""
        for i, connector in enumerate(self._connectors):
            current_stage = self._stage_order[i]
            next_stage = self._stage_order[i + 1]
            
            current_state = self._stages[current_stage].get_state()
            next_state = self._stages[next_stage].get_state()
            
            if current_state.status == 'completed':
                connector.set_completed(True)
                connector.set_active(False)
            elif current_state.status == 'active' and current_state.progress > 80:
                connector.set_active(True)
                connector.set_completed(False)
            else:
                connector.set_active(False)
                connector.set_completed(False)
    
    def get_stage_state(self, stage: PipelineStage) -> Optional[StageState]:
        """Get state of a specific stage"""
        if stage in self._stages:
            return self._stages[stage].get_state()
        return None
    
    def get_all_states(self) -> Dict[PipelineStage, StageState]:
        """Get all stage states"""
        return {stage: widget.get_state() for stage, widget in self._stages.items()}
    
    def reset_all(self):
        """Reset all stages to idle"""
        for stage in self._stage_order:
            state = StageState(stage, 'idle', 0)
            self._stages[stage].set_state(state)
        
        for connector in self._connectors:
            connector.set_active(False)
            connector.set_completed(False)
    
    def _simulate_pipeline(self):
        """Simulate pipeline activity"""
        import random
        
        # Progress through stages
        if self._demo_stage_idx < len(self._stage_order):
            current_stage = self._stage_order[self._demo_stage_idx]
            
            if self._demo_progress < 100:
                # Still processing current stage
                self._demo_progress += random.randint(10, 25)
                self._demo_progress = min(self._demo_progress, 100)
                
                state = StageState(
                    current_stage,
                    'active',
                    self._demo_progress,
                    random.randint(5, 50),
                    f"Processing... {self._demo_progress}%"
                )
                self.set_stage_state(current_stage, state)
                
            else:
                # Complete current stage
                state = StageState(
                    current_stage,
                    'completed',
                    100,
                    random.randint(10, 100),
                    "Complete"
                )
                self.set_stage_state(current_stage, state)
                
                # Move to next stage
                self._demo_stage_idx += 1
                self._demo_progress = 0
                
                # Reset occasionally for demo
                if self._demo_stage_idx >= len(self._stage_order):
                    QTimer.singleShot(2000, self._reset_demo)
        
        # Update throughput
        if random.random() < 0.3:
            throughput = random.uniform(0.5, 5.0)
            self.throughput_label.setText(f"🚀 {throughput:.1f} items/sec")
    
    def _reset_demo(self):
        """Reset pipeline for demo loop"""
        self.reset_all()
        self._demo_stage_idx = 0
        self._demo_progress = 0
