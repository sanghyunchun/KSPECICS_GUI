import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QMessageBox, QSizePolicy
)
from PySide6.QtGui import QMouseEvent, QGuiApplication
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
import numpy as np


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.):
        self.fig = Figure(dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=left,right=right,bottom=bottom,top=top) 
        self.ax.axis('off')
        super().__init__(self.fig)
        self.setParent(parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()

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

    def plots(self,wave,flux):
        self.ax.clear()
        self.ax.plot(wave,flux,'k-')
        self.ax.axis('on')
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
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()

        # 예: 가로/세로 해상도의 80% 크기로 초기화
        screen_width = geometry.width()
        screen_height = geometry.height()

        window_width = int(screen_width * 0.8)
        window_height = int(screen_height * 0.8)

        self.resize(window_width, window_height)
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


        # Button setting
        # Connect RabbitMQ server
        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_define)
        self.ui.pushbtn_connect.setCheckable(True)


        # Guiding
        self.ui.pushbtn_Guiding.clicked.connect(self.autoguiding)


        # Take Image
        self.ui.pushbtn_start_sequence.clicked.connect(self.take_image)

        # Canvas setting
        self.canvas_B=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.B_layout=QVBoxLayout(self.ui.frame_B)
        self.B_layout.addWidget(self.canvas_B)

        self.canvas_R=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.R_layout=QVBoxLayout(self.ui.frame_R)
        self.R_layout.addWidget(self.canvas_R)

        self.canvas_spec_B=MplCanvas(self,dpi=100,left=0.05,right=0.99,bottom=0.15,top=0.99)
        self.Bspec_layout=QVBoxLayout(self.ui.spec_B)
        self.Bspec_layout.addWidget(self.canvas_spec_B)

        self.canvas_spec_R=MplCanvas(self,dpi=100,left=0.05,right=0.99,bottom=0.15,top=0.99)
        self.Rspec_layout=QVBoxLayout(self.ui.spec_R)
        self.Rspec_layout.addWidget(self.canvas_spec_R)

        self.canvas_G1=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G1_layout=QVBoxLayout(self.ui.Guide1)
        self.G1_layout.addWidget(self.canvas_G1)

        self.canvas_G2=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G2_layout=QVBoxLayout(self.ui.Guide2)
        self.G2_layout.addWidget(self.canvas_G2)

        self.canvas_G3=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G3_layout=QVBoxLayout(self.ui.Guide3)
        self.G3_layout.addWidget(self.canvas_G3)

        self.canvas_G4=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G4_layout=QVBoxLayout(self.ui.Guide4)
        self.G4_layout.addWidget(self.canvas_G4)

        self.canvas_G5=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G5_layout=QVBoxLayout(self.ui.Guide5)
        self.G5_layout.addWidget(self.canvas_G5)

        self.canvas_G6=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G6_layout=QVBoxLayout(self.ui.Guide6)
        self.G6_layout.addWidget(self.canvas_G6)



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



    def autoguiding(self):
        cutimgpath='/media/shyunc/DATA/KSpec/KSPEC_ICS/GFA/kspec_gfa_controller/src/img/cutout/'
        guidenum=['1','2','3','4']
        G_canvas=[self.canvas_G1,self.canvas_G2,self.canvas_G3,self.canvas_G4]

        for i,can in enumerate(G_canvas):
            with fits.open(cutimgpath+'cutout_fluxmax_'+str(i+1)+'.fits') as hdul:
                data=hdul[0].data

            self.G_zmin, self.G_zmax = zs.zscale(data)
            can.imshows(data,vmin=self.G_zmin,vmax=self.G_zmax,cmap='gray',origin='lower')
        


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
            

        self.load_spec()



    def load_spec(self):
        waveb,fluxb = np.loadtxt('/media/shyunc/DATA/KSpec/Reduced/SDCH_20190322_009522.txt',skiprows=1,dtype=float,unpack=True,usecols=(0,1))
        self.canvas_spec_B.plots(waveb,fluxb)

        waver,fluxr = np.loadtxt('/media/shyunc/DATA/KSpec/Reduced/SDCK_20190322_009522.txt',skiprows=1,dtype=float,unpack=True,usecols=(0,1))
        self.canvas_spec_R.plots(waver,fluxr)
        self.ui.log.appendPlainText(f"Reduced spectrum loaded.")





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
