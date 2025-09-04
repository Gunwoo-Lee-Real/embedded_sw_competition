#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// INA219 전류/전압 센서
Adafruit_INA219 batteryMonitor(0x44);
WiFiClientSecure client;
HTTPClient http;

// ADC 핀 설정
const int batteryAdcPin = 34;

// 이동 평균 필터 계수
const float alphaVoltageINA = 0.1;
const float alphaCurrentINA = 0.1;
const float alphaVoltageADC = 0.1;

// 전압 기준 및 분배비
const float vRef = 3.3;
const float dividerRatio = 2.0;

// 배터리 용량
const float batteryCapacity_mAh = 3250.0;

// Wi-Fi 정보
#define WIFI_SSID "BOOK-2G934HD7N2 1757"
#define WIFI_PASSWORD "qwer1234"
const char* FIREBASE_URL = "https://firestore.googleapis.com/v1/projects/ev-charge-monitor/databases/(default)/documents/charging/car1";

// 이동 평균 필터 상태 변수
float smoothedINA219Voltage = 0.0;
float smoothedINA219Current = 0.0;
float smoothedBatteryVoltage = 0.0;

// 전류 평균용 히스토리 버퍼
const int currentAvgWindow = 10;
float currentHistory[currentAvgWindow];
int currentIndex = 0;
bool historyFilled = false;

// 함수 선언
float applyEMA(float newValue, float& smoothedValue, float alpha);
float getSmoothedINA219Voltage();
float getSmoothedINA219Current();
float getSmoothedBatteryVoltage();
float getAverageChargingCurrent(float newCurrent);
float calculateBatteryPercentage(float voltage);
String getChargingTimeEstimate(float avgCurrent, float percent);
void connectWiFi();
void uploadToFirestore(float batteryPercent, int remainingTimeMin);

void setup() {
  Serial.begin(115200);

  while (!batteryMonitor.begin()) {
    Serial.println("INA219(0x44) 연결 실패. 재시도 중...");
    delay(1000);
  }
  Serial.println("INA219(0x44) 연결 성공!");

  connectWiFi();
  client.setInsecure();
  http.begin(client, FIREBASE_URL);
  http.addHeader("Content-Type", "application/json");
}

void loop() {
  // 이동 평균 측정값 가져오기
  float busVoltage_V = getSmoothedINA219Voltage();
  float current_mA = getSmoothedINA219Current();
  float batteryVoltage = getSmoothedBatteryVoltage();
  float power_mW = busVoltage_V * (current_mA / 1000.0);
  float batteryPercent = calculateBatteryPercentage(batteryVoltage);
  float avgChargingCurrent = getAverageChargingCurrent(current_mA);
  String chargeTimeStr = getChargingTimeEstimate(avgChargingCurrent, batteryPercent);

  // 출력
  String msg = "전압: " + String(busVoltage_V, 3) + " V, " +
               "전류: " + String(current_mA, 3) + " mA, " +
               "전력: " + String(power_mW, 3) + " mW, " +
               "배터리: " + String(batteryVoltage, 3) + " V (" +
               String(batteryPercent, 1) + "%), " +
               "충전 완료 예상: " + chargeTimeStr;

  Serial.println(msg);

  // 충전 시간 계산
  int estimatedMinutes = 0;
  if (avgChargingCurrent >= 10.0 && batteryPercent < 98.0) {
    float remaining_mAh = batteryCapacity_mAh * ((100.0 - batteryPercent) / 100.0);
    float hours = remaining_mAh / avgChargingCurrent;
    estimatedMinutes = int(hours * 60);
  }

  // Firestore 업로드
  uploadToFirestore(batteryPercent, estimatedMinutes);

  Serial.println("-----------------------------");
  delay(2000);
}

// 🧠 이동 평균 필터
float applyEMA(float newValue, float& smoothedValue, float alpha) {
  if (smoothedValue == 0.0 || isnan(newValue)) smoothedValue = newValue;
  else smoothedValue = alpha * newValue + (1.0 - alpha) * smoothedValue;
  return smoothedValue;
}

float getSmoothedINA219Voltage() {
  float raw = batteryMonitor.getBusVoltage_V();
  return applyEMA(raw, smoothedINA219Voltage, alphaVoltageINA);
}

float getSmoothedINA219Current() {
  float raw = batteryMonitor.getCurrent_mA();
  return applyEMA(raw, smoothedINA219Current, alphaCurrentINA);
}

float getSmoothedBatteryVoltage() {
  long total = 0;
  const int samples = 20;
  for (int i = 0; i < samples; i++) {
    total += analogRead(batteryAdcPin);
    delayMicroseconds(500);
  }
  float avgAdc = total / float(samples);
  float voltage = (avgAdc / 4095.0) * vRef * dividerRatio;
  return applyEMA(voltage, smoothedBatteryVoltage, alphaVoltageADC);
}

// 충전 퍼센트 계산
float calculateBatteryPercentage(float voltage) {
  float percent = (voltage - 2.95) / (4.2 - 2.95) * 100.0;
  if (percent > 100.0) return 100.0;
  if (percent < 0.0) return 0.0;
  return percent;
}

// 충전 시간 추정
String getChargingTimeEstimate(float avgCurrent_mA, float percent) {
  if (avgCurrent_mA < 1.0 || percent >= 98.0) return "--";
  float remaining_mAh = batteryCapacity_mAh * ((100.0 - percent) / 100.0);
  float hours = remaining_mAh / avgCurrent_mA;
  int h = int(hours);
  int m = int((hours - h) * 60);
  return String(h) + "h " + String(m) + "m";
}

// 전류 평균 계산
float getAverageChargingCurrent(float newCurrent) {
  currentHistory[currentIndex] = newCurrent;
  currentIndex = (currentIndex + 1) % currentAvgWindow;
  if (currentIndex == 0) historyFilled = true;

  float total = 0;
  int count = historyFilled ? currentAvgWindow : currentIndex;
  for (int i = 0; i < count; i++) total += currentHistory[i];

  return total / count;
}

// WiFi 연결
void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi 연결 중");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi 연결 완료");
}

// Firestore 업로드
void uploadToFirestore(float batteryPercent, int remainingTimeMin) {
  if (WiFi.status() == WL_CONNECTED) {
    String json = "{\"fields\": {\"batteryLevel\": {\"doubleValue\": \"" + String(batteryPercent) +
                   "\"}, \"remainingTime\": {\"integerValue\": \"" + String(remainingTimeMin) + "\"}}}";

    Serial.println("📦 요청 바디:");
    Serial.println(json);

    int httpResponseCode = http.PATCH(json);
    if (httpResponseCode > 0) {
      Serial.print("📤 업로드 성공: ");
      Serial.println(httpResponseCode);
    } else {
      Serial.print("❌ 업로드 실패: ");
      Serial.println(httpResponseCode);
    }
  } else {
    Serial.println("📡 WiFi 연결 안 됨");
  }
}
