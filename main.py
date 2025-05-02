import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import *
from ui_temp import Ui_MainWindow
from qasync import QEventLoop, asyncSlot
from Lib.AMQ import AMQclass
import Lib.mkmessage as mkmsg
#from LAMP.lampcli import handle_lamp
import json


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

        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_define)
        self.ui.pushbtn_connect.setCheckable(True)

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
        self.ui.log_2.appendPlainText(react)
        #self.processlog.append(react)
        react = await self.ICS_client.define_producer()
        self.ui.log.appendPlainText(react)
        await self.ICS_client.define_consumer()
        asyncio.create_task(self.wait_for_response())



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
                    print(f'put in {response_data["inst"]}: {response_data}')
                    await queue_map[response_data['inst']].put(response_data)
                elif response_data['inst'] == 'SPEC' and response_data['process'] == 'Done':
                    await self.SPEC_response_queue.put(response_data)
                else:
                    await self.response_queue.put(response_data)
                    print(f'response_queue formation: {response_data}')
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

    def load_data(self, 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()
#    sys.exit(app.exec())
