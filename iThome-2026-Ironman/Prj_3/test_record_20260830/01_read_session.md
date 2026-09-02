# Day 19 實測紀錄 — 第一階段（讀取）

開始時間：2026-08-30 14:25:10
環境：Windows 11 / Python 3.13.15 / bleak 2.0.0（conda env `nb_ble`）
模式：唯讀，全程沒有寫入任何 characteristic，沒有嘗試認證。

---

## 1. 掃描（20 秒）

掃到 20 個裝置，其中有名稱的 2 個。

  Mi Smart Band 6              C2:45:**:**:**:2E  RSSI  -60 dBm  <== 疑似小米/華米裝置
      廣播服務: fee0
      廠商資料 0x0157: 02ffffffffffffffffffffffffffffffff03c245******2e
  上面                           CD:D2:**:**:**:CB  RSSI  -82 dBm
      廣播服務: fe0f

## 2. 連線

目標：Mi Smart Band 6  C2:45:**:**:**:2E  RSSI -60 dBm
連線成功，耗時 9.9 秒。

## 3. GATT 完整結構

SERVICE 00001800-0000-1000-8000-00805f9b34fb  通用存取 (GAP)
  CHAR 00002a00-0000-1000-8000-00805f9b34fb  [read]  handle=2
       裝置名稱
  CHAR 00002a01-0000-1000-8000-00805f9b34fb  [read]  handle=4
       Appearance
  CHAR 00002a04-0000-1000-8000-00805f9b34fb  [read]  handle=6
       Peripheral Preferred Connection Parameters

SERVICE 00001801-0000-1000-8000-00805f9b34fb  通用屬性 (GATT)

SERVICE 0000180a-0000-1000-8000-00805f9b34fb  裝置資訊 (免認證可讀)
  CHAR 00002a25-0000-1000-8000-00805f9b34fb  [read]  handle=10
       序號
  CHAR 00002a27-0000-1000-8000-00805f9b34fb  [read]  handle=12
       硬體版本
  CHAR 00002a28-0000-1000-8000-00805f9b34fb  [read]  handle=14
       軟體版本
  CHAR 00002a23-0000-1000-8000-00805f9b34fb  [read]  handle=16
       System ID
  CHAR 00002a50-0000-1000-8000-00805f9b34fb  [read]  handle=18
       PnP ID
  CHAR 00000014-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=20
       Hardcopy Data Channel
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

SERVICE 00001530-0000-3512-2118-0009af100700  未知
  CHAR 00001531-0000-3512-2118-0009af100700  [notify,write]  handle=24
       未知
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00001532-0000-3512-2118-0009af100700  [write-without-response]  handle=27
       未知

SERVICE 00001811-0000-1000-8000-00805f9b34fb  Alert Notification Service
  CHAR 00002a46-0000-1000-8000-00805f9b34fb  [read,write]  handle=30
       New Alert
       DESC 00002901-0000-1000-8000-00805f9b34fb  Characteristic User Description
  CHAR 00002a44-0000-1000-8000-00805f9b34fb  [notify,read,write]  handle=33
       Alert Notification Control Point
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

SERVICE 00001802-0000-1000-8000-00805f9b34fb  Immediate Alert
  CHAR 00002a06-0000-1000-8000-00805f9b34fb  [write-without-response]  handle=37
       Alert Level

SERVICE 0000180d-0000-1000-8000-00805f9b34fb  心率 (通常需認證)
  CHAR 00002a37-0000-1000-8000-00805f9b34fb  [notify]  handle=40
       心率量測 (notify)
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00002a39-0000-1000-8000-00805f9b34fb  [read,write]  handle=43
       心率控制點 (需認證)

SERVICE 0000fee0-0000-1000-8000-00805f9b34fb  華米主服務 (私有，多數需認證)
  CHAR 00002a2b-0000-1000-8000-00805f9b34fb  [notify,read,write]  handle=46
       目前時間 (手環時鐘)
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000001-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=49
       Huami: 韌體上傳控制
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000002-0000-3512-2118-0009af100700  [notify]  handle=52
       Huami: 韌體資料
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000003-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=55
       Huami: 使用者設定
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00002a04-0000-1000-8000-00805f9b34fb  [notify,read,write-without-response]  handle=58
       Peripheral Preferred Connection Parameters
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000004-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=61
       Huami: 活動資料
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000005-0000-3512-2118-0009af100700  [notify]  handle=64
       Huami: 資料傳輸控制
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000006-0000-3512-2118-0009af100700  [notify,read]  handle=67
       Huami: 電池詳情
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000007-0000-3512-2118-0009af100700  [notify,read]  handle=70
       Huami: 即時步數/活動
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000008-0000-3512-2118-0009af100700  [notify,write]  handle=73
       Huami: 配對
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000010-0000-3512-2118-0009af100700  [notify]  handle=76
       Huami: 感測器資料
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000020-0000-3512-2118-0009af100700  [notify,read,write-without-response]  handle=79
       未知
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 0000000e-0000-3512-2118-0009af100700  [write]  handle=82
       Huami: 感測器控制
       DESC 00002901-0000-1000-8000-00805f9b34fb  Characteristic User Description
  CHAR 0000000f-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=85
       BNEP
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000011-0000-3512-2118-0009af100700  [notify,read,write-without-response]  handle=88
       HIDP
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000012-0000-3512-2118-0009af100700  [notify,read,write-without-response]  handle=91
       Hardcopy Control Channel
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000013-0000-3512-2118-0009af100700  [notify,read,write]  handle=94
       未知
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000016-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=97
       Hardcopy Notification
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 00000017-0000-3512-2118-0009af100700  [notify,write-without-response]  handle=100
       AVCTP
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

SERVICE 0000fee1-0000-1000-8000-00805f9b34fb  華米認證服務
  CHAR 00000009-0000-3512-2118-0009af100700  [notify,read,write-without-response]  handle=104
       Huami: 認證 (auth challenge)
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration
  CHAR 0000fedd-0000-1000-8000-00805f9b34fb  [write]  handle=107
       Jawbone
  CHAR 0000fede-0000-1000-8000-00805f9b34fb  [read]  handle=109
       Coin: Inc.
  CHAR 0000fedf-0000-1000-8000-00805f9b34fb  [read]  handle=111
       Design SHIFT
  CHAR 0000fed0-0000-1000-8000-00805f9b34fb  [read,write]  handle=113
       Apple: Inc.
  CHAR 0000fed1-0000-1000-8000-00805f9b34fb  [read,write]  handle=115
       Apple: Inc.
  CHAR 0000fed2-0000-1000-8000-00805f9b34fb  [read]  handle=117
       Apple: Inc.
  CHAR 0000fed3-0000-1000-8000-00805f9b34fb  [read,write]  handle=119
       Apple: Inc.
  CHAR 0000fec1-0000-3512-2118-0009af100700  [notify,read,write]  handle=121
       KDDI Corporation
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

SERVICE 0000180f-0000-1000-8000-00805f9b34fb  電池
  CHAR 00002a19-0000-1000-8000-00805f9b34fb  [notify,read]  handle=125
       電池電量 (%)
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

SERVICE 00003802-0000-1000-8000-00805f9b34fb  Vendor specific
  CHAR 00004a02-0000-1000-8000-00805f9b34fb  [notify,read,write]  handle=151
       Vendor specific
       DESC 00002902-0000-1000-8000-00805f9b34fb  Client Characteristic Configuration

合計：服務 11、特徵 46、描述元 28，節點總數 85

## 4. 讀取所有帶 read 屬性的 characteristic

00002a00-0000-1000-8000-00805f9b34fb  裝置名稱
      4d 69 20 53 6d 61 72 74 20 42 61 6e 64 20 36  |Mi Smart Band 6|
      => Mi Smart Band 6
00002a01-0000-1000-8000-00805f9b34fb  Appearance
      c1 03  |..|
00002a04-0000-1000-8000-00805f9b34fb  Peripheral Preferred Connection Parameters
      06 00 50 00 00 00 f4 01  |..P.....|
00002a25-0000-1000-8000-00805f9b34fb  序號
      33 32 2a 2a 2a 2a 2a 2a 2a 2a 2a 2a 37 34  |32**********74|
      => 32**********74
00002a27-0000-1000-8000-00805f9b34fb  硬體版本
      56 30 2e 38 32 2e 31 31 34 2e 33  |V0.82.114.3|
      => V0.82.114.3
00002a28-0000-1000-8000-00805f9b34fb  軟體版本
      56 31 2e 30 2e 36 2e 32 30  |V1.0.6.20|
      => V1.0.6.20
00002a23-0000-1000-8000-00805f9b34fb  System ID
      c2 45 ** ** ** ** ** 2e  |.E......|
00002a50-0000-1000-8000-00805f9b34fb  PnP ID
      01 57 01 5b 00 01 01  |.W.[...|
00002a46-0000-1000-8000-00805f9b34fb  New Alert
      05  |.|
00002a44-0000-1000-8000-00805f9b34fb  Alert Notification Control Point
      00  |.|
00002a39-0000-1000-8000-00805f9b34fb  心率控制點 (需認證)
      讀取被拒: Could not read characteristic handle 43: Protocol Error 0x02: Read Not Permitted
00002a2b-0000-1000-8000-00805f9b34fb  目前時間 (手環時鐘)
      ea 07 08 1e 0e 19 29 07 00 00 20  |......)... |
      => 2026-08-30 14:25:41 星期日
00002a04-0000-1000-8000-00805f9b34fb  Peripheral Preferred Connection Parameters
      30 00 30 00 00 00 c0 03  |0.0.....|
00000006-0000-3512-2118-0009af100700  Huami: 電池詳情
      0f 4e 00 ea 07 08 1c 0e 3b 17 20 ea 07 08 1c 10 09 20 20 63  |.N......;. ......  c|
      => 電量 78 %，狀態 未充電，時間戳1 2026-08-28 14:59:23 (UTC+8)，時間戳2 2026-08-28 16:09:32 (UTC+8)，上次充電結束電量 99 %
00000007-0000-3512-2118-0009af100700  Huami: 即時步數/活動
      讀取被拒: Could not read characteristic handle 70: Protocol Error 0x02: Read Not Permitted
00000020-0000-3512-2118-0009af100700  未知
      0b  |.|
00000011-0000-3512-2118-0009af100700  HIDP
      讀取被拒: Could not read characteristic handle 88: Protocol Error 0x02: Read Not Permitted
00000012-0000-3512-2118-0009af100700  Hardcopy Control Channel
      02  |.|
00000013-0000-3512-2118-0009af100700  未知
        ||
00000009-0000-3512-2118-0009af100700  Huami: 認證 (auth challenge)
      01 00 00 00  |....|
0000fede-0000-1000-8000-00805f9b34fb  Coin: Inc.
        ||
0000fedf-0000-1000-8000-00805f9b34fb  Design SHIFT
      01  |.|
0000fed0-0000-1000-8000-00805f9b34fb  Apple: Inc.
        ||
0000fed1-0000-1000-8000-00805f9b34fb  Apple: Inc.
        ||
0000fed2-0000-1000-8000-00805f9b34fb  Apple: Inc.
        ||
0000fed3-0000-1000-8000-00805f9b34fb  Apple: Inc.
        ||
0000fec1-0000-3512-2118-0009af100700  KDDI Corporation
        ||
00002a19-0000-1000-8000-00805f9b34fb  電池電量 (%)
      4e  |N|
      => 78 %
00004a02-0000-1000-8000-00805f9b34fb  Vendor specific
      讀取被拒: Could not read characteristic handle 151: Protocol Error 0x02: Read Not Permitted

成功讀取 25 個，被拒 4 個。

被拒清單（原始錯誤字串，未加工）：
  00002a39-0000-1000-8000-00805f9b34fb  Could not read characteristic handle 43: Protocol Error 0x02: Read Not Permitted
  00000007-0000-3512-2118-0009af100700  Could not read characteristic handle 70: Protocol Error 0x02: Read Not Permitted
  00000011-0000-3512-2118-0009af100700  Could not read characteristic handle 88: Protocol Error 0x02: Read Not Permitted
  00004a02-0000-1000-8000-00805f9b34fb  Could not read characteristic handle 151: Protocol Error 0x02: Read Not Permitted

## 5. 手環摘要（選項 9 的七個欄位）

  裝置名稱   Mi Smart Band 6
  序號     32**********74
  硬體版本   V0.82.114.3
  韌體版本   V1.0.6.20
  電池電量   78 %
  電池詳情   電量 78 %，狀態 未充電，時間戳1 2026-08-28 14:59:23 (UTC+8)，時間戳2 2026-08-28 16:09:32 (UTC+8)，上次充電結束電量 99 %
  手環時間   2026-08-30 14:25:44 星期日
  即時步數   禁止直接讀取，請用選項 8 監看 notify

## 6. 斷線

已主動斷線，本階段結束。

結束時間：2026-08-30 14:25:45
