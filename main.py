import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QMessageBox
)
from PySide6.QtGui import QMouseEvent
from ui_temp import Ui_MainWindow
from qasync import QEventLoop, asyncSlot
from astropy.io import fits
from Lib.AMQ import AMQclass
import Lib.mkmessage as mkmsg
import Lib.zscale as zs
#from LAMP.lampcli import handle_lamp
import json
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from SPECTRO.speccli import handle_spec


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None,width=5,height=5,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.):
        self.fig = Figure(figsize=(width, height),dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.00,right=1.,bottom=0.0,top=1.) 
        self.ax.axis('off')
        super().__init__(self.fig)
        self.setParent(parent)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        self._is_dragging = False
        self._last_mouse_pos = None

        # Set inital axis range
        self._initial_xlim = None
        self._initial_ylim = None

    def imshows(self, data, **kwargs):
        self.ax.clear()
        self.ax.imshow(data, **kwargs)
        self.ax.axis('on')
        self._initial_xlim = self.ax.get_xlim()
        self._initial_ylim = self.ax.get_ylim()
        self.draw()

    def wheelEvent(self, event):
        # Expand and contract
        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()
        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1

        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2
        x_range = (x_max - x_min) * zoom_factor
        y_range = (y_max - y_min) * zoom_factor

        self.ax.set_xlim([x_center - x_range / 2, x_center + x_range / 2])
        self.ax.set_ylim([y_center - y_range / 2, y_center + y_range / 2])
        self.draw()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._last_mouse_pos = event.position()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click for reset
            if self._initial_xlim and self._initial_ylim:
                self.ax.set_xlim(self._initial_xlim)
                self.ax.set_ylim(self._initial_ylim)
                self.draw()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and self._last_mouse_pos:
            current_pos = event.position()
            dx = current_pos.x() - self._last_mouse_pos.x()
            dy = current_pos.y() - self._last_mouse_pos.y()

            x_min, x_max = self.ax.get_xlim()
            y_min, y_max = self.ax.get_ylim()
            x_range = x_max - x_min
            y_range = y_max - y_min

            self.ax.set_xlim(x_min - dx * x_range / self.width(), x_max - dx * x_range / self.width())
            self.ax.set_ylim(y_min + dy * y_range / self.height(), y_max + dy * y_range / self.height())
            self.draw()

            self._last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.response_queue = asyncio.Queue()
        self.GFA_response_queue = asyncio.Queue()
        self.ADC_response_queue = asyncio.Queue()
        self.SPEC_response_queue = asyncio.Queue()


#Make timer (LT & UTC) 
        self.datetime = QDateTime.currentDateTime().toString()
        #self.lcd.display(datetime)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.timeout)
        self.setWindowTitle('QTimer')

        self.timer.start()

        # Connect RabbitMQ server
        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_define)
        self.ui.pushbtn_connect.setCheckable(True)

        # Take Image
        self.ui.pushbtn_start_sequence.clicked.connect(self.take_image)

        self.canvas_B=MplCanvas(self,width=5,height=5,dpi=100,left=0.00,right=0.8,bottom=0.0,top=0.8)
        self.canvas_layout=QVBoxLayout(self.ui.frame_B)
        self.canvas_layout.addWidget(self.canvas_B)

        self.canvas_R=MplCanvas(self,width=5,height=5,dpi=100,left=0.00,right=0.8,bottom=0.0,top=0.8)
        self.canvas_layout=QVBoxLayout(self.ui.frame_R)
        self.canvas_layout.addWidget(self.canvas_R)

    @asyncSlot()
    async def rabbitmq_define(self):
        # Connect RabbitMQ
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        self.ICS_client = AMQclass(
            kspecinfo['RabbitMQ']['ip_addr'],
            kspecinfo['RabbitMQ']['idname'],
            kspecinfo['RabbitMQ']['pwd'],
            'ICS', 'ics.ex'
        )

        react = await self.ICS_client.connect()
        self.ui.log.appendPlainText(react)
#        self.ui.log_2.appendPlainText(react)
        #self.processlog.append(react)
        react = await self.ICS_client.define_producer()
        self.ui.log.appendPlainText(react)
        await self.ICS_client.define_consumer()
        asyncio.create_task(self.wait_for_response())


    @asyncSlot()
    async def take_image(self):
        await handle_spec('getobj 3 1', self.ICS_client)
        self.ui.log.appendPlainText("sent message to device 'SPEC'. message: Get 1 bias images.")
        msg=await self.response_queue.get()
#        self.ui.log.appendPlainText(f"{msg['file']}")

        filename=msg['file']

        self.reload_img(filename)


    def reload_img(self,filename):
        rawdir='/media/shyunc/DATA/KSpec/RAWDATA/'
        filepath=os.path.join(rawdir,filename)

        try:
            with fits.open(filepath) as hdul:
                data = hdul[0].data

            # Z-scale 계산
            self.zmin, self.zmax = zs.zscale(data)

            # 기존 캔버스 초기화
            self.canvas_B.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

            self.canvas_R.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

#            self.canvas.ax.axis('off')
#            self.canvas.draw()

            self.ui.log.appendPlainText(f"Loaded image: {filename}")

        except Exception as e:
            print(f"[ERROR] Could not load image {filepath}: {e}")
            self.ui.log.appendPlainText(f"Failed to load image: {e}")




    async def wait_for_response(self):
        """
        Waits for responses from the K-SPEC sub-system and distributes then appropriately.
        """
        while True:
            try:
                response = await self.ICS_client.receive_message("ICS")
                response_data = json.loads(response)
                inst=response_data['inst']
                message=response_data.get('message','No message')
                self.ui.log.appendPlainText(message)
                #self.processlog.append(message)

                if isinstance(message,dict):
                    message = json.dumps(message, indent=2)
                    print(f'\033[94m[ICS] received from {inst}: {message}\033[0m\n', flush=True)
                else:
                    print(f'\033[94m[ICS] received from {inst}: {response_data["message"]}\033[0m\n', flush=True)

                queue_map = {"GFA": self.GFA_response_queue, "ADC": self.ADC_response_queue, "SPEC": self.SPEC_response_queue}
                if response_data['inst'] in queue_map and response_data['process'] == 'ING':
#                    print(f'put in {response_data["inst"]}: {response_data}')
                    await queue_map[response_data['inst']].put(response_data)
#                elif response_data['inst'] == 'SPEC' and response_data['process'] == 'Done':
#                    await self.SPEC_response_queue.put(response_data)
                else:
                    await self.response_queue.put(response_data)
#                    print(f'response_queue formation: {response_data}')
            except Exception as e:
                print(f"Error in wait_for_response: {e}", flush=True)
        

#Close Event : to prevent to close the window easily
    def closeEvent(self, QCloseEvent):
        re = QMessageBox.question(self, "Close the program", "Are you sure you want to quit?",
                    QMessageBox.Yes|QMessageBox.No)

        if re == QMessageBox.Yes:
            QCloseEvent.accept()
        else:
            QCloseEvent.ignore() 

    def timeout(self):
        sender = self.sender()
        currentTime = QDateTime.currentDateTime().toString('yyyy.MM.dd, hh:mm:ss')
        currentutc = QDateTime.currentDateTimeUtc().toString('yyyy.MM.dd, hh:mm:ss')
        #print(currentTime)
        if id(sender) == id(self.timer):
            self.ui.lcd_lt.display(currentTime)
            self.ui.lcd_utc.display(currentutc)

#    def load_data(self, 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()
#    sys.exit(app.exec())
