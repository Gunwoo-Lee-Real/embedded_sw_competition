import torch
import cv2
import time
import pathlib
import numpy as np
from models.common import DetectMultiBackend
from utils.general import non_max_suppression
from utils.augmentations import letterbox

pathlib.WindowsPath = pathlib.PosixPath

# scale_coords 함수 직접 정의 (기존 함수 그대로)
def scale_coords(img1_shape, coords, img0_shape, ratio_pad=None):
    if ratio_pad is None:
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    coords[:, [0, 2]] -= pad[0]  # x padding
    coords[:, [1, 3]] -= pad[1]  # y padding
    coords[:, :4] /= gain
    coords[:, 0].clamp_(0, img0_shape[1])  # x1
    coords[:, 1].clamp_(0, img0_shape[0])  # y1
    coords[:, 2].clamp_(0, img0_shape[1])  # x2
    coords[:, 3].clamp_(0, img0_shape[0])  # y2
    return coords

def run(shared_dict):
    model = DetectMultiBackend('best1.pt', device='cpu')
    names = model.names
    stride = model.stride

    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # 전처리
        img = letterbox(frame, new_shape=640, stride=stride)[0]
        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR → RGB, HWC → CHW
        img = np.ascontiguousarray(img)
        img = torch.from_numpy(img).to('cpu').float() / 255.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # 추론
        pred = model(img)
        det = non_max_suppression(pred, conf_thres=0.25, iou_thres=0.45)[0]

        rendered = frame.copy()
        classes_detected = set()  # 프레임마다 초기화

        if det is not None and len(det):
            det[:, :4] = scale_coords(img.shape[2:], det[:, :4], frame.shape).round()
            for *xyxy, conf, cls in det:
                class_name = names[int(cls)]
                classes_detected.add(class_name)

                label = f"{class_name} {conf:.2f}"
                cv2.rectangle(rendered, (int(xyxy[0]), int(xyxy[1])), (int(xyxy[2]), int(xyxy[3])), (0, 255, 0), 2)
                cv2.putText(rendered, label, (int(xyxy[0]), int(xyxy[1]) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # 감지 결과 업데이트
        current_time = time.time()
        shared_dict['car_detected'] = 'Car' in classes_detected
        shared_dict['ev_detected'] = 'EV license plate' in classes_detected
        shared_dict['normal_detected'] = 'Normal license plate' in classes_detected

        # Normal plate → EV인지 아닌지 판단 기준으로 사용
        if shared_dict['car_detected'] and shared_dict['ev_detected']:
            shared_dict['last_detected_time'] = current_time

        # 디버그 출력
        print(f"[YOLO] Car={shared_dict['car_detected']}, EV={shared_dict['ev_detected']}, Last={shared_dict['last_detected_time']:.2f}")

        # 결과 시각화
        cv2.imshow('YOLOv5 Detection', rendered)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
