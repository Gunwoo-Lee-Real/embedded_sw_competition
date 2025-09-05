# main.py
from multiprocessing import Process, Manager
from yolo_detect1 import run as yolo_run
from overall_4 import run as overall_run

if __name__ == '__main__':
    manager = Manager()
    shared_dict = manager.dict({
        'car_detected': False,
        'ev_detected': False,
        'last_detected_time': 0
    })

    p1 = Process(target=yolo_run, args=(shared_dict,))
    p2 = Process(target=overall_run, args=(shared_dict,))

    p1.start()
    p2.start()

    p1.join()
    p2.join()
