def run(shared_dict):
    import time
    import torch
    import RPi.GPIO as GPIO
    import board
    import busio
    from RPLCD.i2c import CharLCD
    import requests

    # DNN 모델 정의 및 불러오기
    class MLP_optimize(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc1 = torch.nn.Linear(2, 64)
            self.fc2 = torch.nn.Linear(64, 32)
            self.fc3 = torch.nn.Linear(32, 16)
            self.fc4 = torch.nn.Linear(16, 2)

        def forward(self, x):
            x = torch.nn.functional.relu(self.fc1(x))
            x = torch.nn.functional.relu(self.fc2(x))
            x = torch.nn.functional.relu(self.fc3(x))
            return self.fc4(x)

    model = MLP_optimize()
    model.load_state_dict(torch.load('motor_predictor.pt', map_location=torch.device('cpu')))
    model.eval()

    lcd = CharLCD('PCF8574', 0x27)
    lcd.clear()
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    TRIG1, ECHO1 = 23, 24
    TRIG2, ECHO2 = 27, 4
    STEP_PIN1, DIR_PIN1, SLEEP_PIN1 = 14, 15, 18
    STEP_PIN2, DIR_PIN2, SLEEP_PIN2 = 20, 21, 16
    RELAY_PIN = 17

    for pin in [TRIG1, TRIG2]:
        GPIO.setup(pin, GPIO.OUT)
    for pin in [ECHO1, ECHO2]:
        GPIO.setup(pin, GPIO.IN)
    for pin in [STEP_PIN1, DIR_PIN1, SLEEP_PIN1, STEP_PIN2, DIR_PIN2, SLEEP_PIN2, RELAY_PIN]:
        GPIO.setup(pin, GPIO.OUT)

    GPIO.output(RELAY_PIN, GPIO.LOW)


    # Firestore에서 충전 상태 읽기
    def get_charging_data():
        try:
            url = "https://firestore.googleapis.com/v1/projects/ev-charge-monitor/databases/(default)/documents/charging/car1"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                fields = data.get("fields", {})

                # stringValue로 읽기
                battery_str = fields.get("batteryLevel", {}).get("doubleValue", "0")
                minutes_str = fields.get("remainingTime", {}).get("integerValue", "0")

                battery = float(battery_str)    
                minutes = int(minutes_str)
                return battery, minutes
            else:
                print("❌ Firestore 요청 실패:", response.status_code)
                return None, None
        except Exception as e:
            print("❌ Firestore 예외 발생:", e)
            return None, None


    def get_distance(trig, echo):
        GPIO.output(trig, True)
        time.sleep(0.00001)
        GPIO.output(trig, False)
        pulse_start = time.time()
        timeout = pulse_start + 0.05
        while GPIO.input(echo) == 0 and time.time() < timeout:
            pulse_start = time.time()
        pulse_end = time.time()
        while GPIO.input(echo) == 1 and time.time() < timeout:
            pulse_end = time.time()
        return round((pulse_end - pulse_start) * 17150, 2)

    def move_motor(pin_dir, pin_step, pin_sleep, direction, steps):
        GPIO.output(pin_sleep, GPIO.HIGH)
        GPIO.output(pin_dir, direction)
        for _ in range(steps):
            GPIO.output(pin_step, GPIO.HIGH)
            time.sleep(0.001)
            GPIO.output(pin_step, GPIO.LOW)
            time.sleep(0.001)
        GPIO.output(pin_sleep, GPIO.LOW)

    try:
        print("start")
        lcd.write_string("System Ready")
        time.sleep(4)
        #lcd.clear()
        print("start2")

        detection_start_time = None  # 루프 바깥에서 초기화 필요

        while True:
            if shared_dict['car_detected'] and shared_dict['ev_detected']:
                if detection_start_time is None:
                    detection_start_time = time.time()
                elif time.time() - detection_start_time >= 5:
                    lcd.clear()
                    lcd.write_string("Parking...")
                    time.sleep(5)
                    print("start3")

                    d1 =  get_distance(TRIG1, ECHO1)
                    d2 =  get_distance(TRIG2, ECHO2)
                    input_tensor = torch.tensor([[d1, d2]], dtype=torch.float32)

                    with torch.no_grad():
                        motor_steps = model(input_tensor).numpy().astype(int)[0]

                    move_motor(DIR_PIN1, STEP_PIN1, SLEEP_PIN1, GPIO.LOW, motor_steps[0])
                    move_motor(DIR_PIN2, STEP_PIN2, SLEEP_PIN2, GPIO.LOW, motor_steps[1])
                    GPIO.output(RELAY_PIN, GPIO.HIGH)

                    lcd.clear()
                    lcd.write_string("Charging...")
                    time.sleep(2)

                    while True:
                        
                        battery, minutes = get_charging_data()
                        if battery is not None and minutes is not None:
                            lcd.clear()
                            lcd.write_string(f"Batt: {battery:.1f}%")
                            lcd.cursor_pos = (1, 0)
                            lcd.write_string(f"Time: {minutes}min")
                        else:
                            lcd.clear()
                            lcd.write_string("Data Error")
                        time.sleep(3)
  
                        d1 =  get_distance(TRIG1, ECHO1)
                        d2 =  get_distance(TRIG2, ECHO2)
                        if d1 > 30 and d2 > 30:
                            GPIO.output(RELAY_PIN, GPIO.LOW)
                            lcd.clear()
                            lcd.write_string("Leaving...")
                            time.sleep(2)
                            move_motor(DIR_PIN2, STEP_PIN2, SLEEP_PIN2, GPIO.HIGH, motor_steps[1])
                            move_motor(DIR_PIN1, STEP_PIN1, SLEEP_PIN1, GPIO.HIGH, motor_steps[0])

                            lcd.clear()
                            lcd.write_string("System Ready")
                            shared_dict['car_detected'] = False
                            shared_dict['ev_detected'] = False
                            shared_dict['last_detected_time'] = 0
                            detection_start_time = None  # 타이머 초기화
                            time.sleep(3)
                            #lcd.clear()
                            break
            else:
        # 둘 중 하나라도 감지 안 되면 타이머 초기화
                detection_start_time = None


    except KeyboardInterrupt:
        print("종료합니다.")
    finally:
        lcd.clear()
        GPIO.cleanup()
