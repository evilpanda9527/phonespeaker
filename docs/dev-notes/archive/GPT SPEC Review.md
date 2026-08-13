我看完這份 `SPEC.md` 了。整體來說，**這個專案的核心架構是可行的**，而且 WiFi 方案最合理；USB 也可以做，但目前 SPEC 裡有幾個地方我認為需要修正，否則之後真的開始寫程式，很容易遇到「設計看起來可行、實機卻連不上」的問題。

尤其是你一開始給的真正需求是：

> **USB / BT / WiFi 三種方式，使用者不在乎手機 APP 和 PC APP 誰先開，連線成功後就直接當 PC Speaker。**

這個需求我會把它當最高優先級來檢查，而不是單純照 SPEC 接受。

---

# **先講結論**

| 功能 | 可行性 | 我的判斷 |
| ----- | ----- | ----- |
| WiFi → 手機 Speaker | 🟢 很可行 | 最容易成功 |
| USB → 手機 Speaker | 🟡 可行，但要修改/驗證 | 最大問題是 USB tethering \+ 探索 |
| Bluetooth → 手機 Speaker | 🟡 可行，但現在 SPEC 寫得太模糊 | M2 要重新確認 BT 架構 |
| PC 擷取系統聲音 | 🟢 可行 | WASAPI loopback 正確 |
| TCP 傳 PCM | 🟢 可行 | 架構簡單 |
| Android AudioTrack 播放 | 🟢 可行 | 正確方向 |
| PC 自動靜音 | 🟢 可行 | pycaw 可以 |
| 不限 App 開啟順序 | 🟢 可以做到 | 需要設計 reconnect/discovery |
| 低延遲 | 🟢 可以做到 | 但目前估算方式有問題 |
| 48k/2ch/S16LE 永遠固定 | 🟡 有風險 | 建議修改 |
| mDNS 用於 USB RNDIS | 🟡 必須實機驗證 | SPEC 已經有寫這個風險 |

---

# **一、最重要：你的需求跟目前 SPEC 有一點不一樣**

你原本的需求：

> USB：USB 連接 → 手機 APP \+ PC APP → 自動輸出

但 SPEC 寫的是：

> **手機先開「USB 網路共享」→ 接 USB 線 → 兩端開 app**

這兩個其實不完全一樣。

目前 SPEC 的 USB 本質上是：

**USB 線 → USB Tethering → RNDIS 網路 → TCP → 手機**

而不是：

**USB Cable → USB Audio → 手機**

所以你必須接受一個事實：

### **USB 模式需要 Android 開啟 USB 網路共享**

否則 PC 和手機之間沒有 IP 網路，TCP server/client 沒有路徑。

而 Android App 一般**不能隨便替使用者偷偷開啟 USB tethering**。

所以如果你的要求是：

> 「我只插 USB 線，什麼設定都不用碰」

那目前這個 USB 架構**做不到完全自動**。

但如果你接受：

> 「手機 USB 網路共享已經開啟，之後插線、開 APP 就自動」

那就完全合理。

---

# **二、WiFi 是這個專案最漂亮的部分**

目前：

> PC \= TCP Server  
> Android \= TCP Client  
> PC 使用 mDNS 廣播  
> Android 使用 NsdManager 找 PC

這個架構很好。

使用者：

1. PC 開 App  
2. 手機開 App  
3. 手機搜尋 `_phonespeaker._tcp`  
4. 找到 PC  
5. TCP connect  
6. PC 開始送音訊  
7. Android 播放

反過來：

1. 手機先開 App  
2. 找不到 PC  
3. 等待 discovery  
4. PC 後來開 App  
5. mDNS 出現  
6. 手機自動找到  
7. TCP connect  
8. 播放

所以你要求的：

> **不在乎 APP 開啟順序**

WiFi 完全可以做到。

---

# **三、TCP PCM 的設計也沒什麼大問題**

目前：

4 bytes length  
\+  
PCM data

每 20ms：

48,000 Hz  
2 channel  
16 bit

48000 × 0.02 × 2 × 2  
\= 3840 bytes

這個計算是對的。

而且你目前不做 codec、不做壓縮、不做時間戳，對 **M1** 來說是非常合理的。

---

# **四、但「固定 48k/2ch/S16LE」我建議修改**

這是我認為 SPEC 裡一個比較重要的技術風險。

現在寫：

> WASAPI loopback 固定 48k/2ch/S16LE

問題是：

**Windows 使用者的預設播放裝置不一定是 48k / stereo / 16-bit。**

例如可能是：

* 44.1 kHz  
* 48 kHz  
* 96 kHz  
* 24-bit  
* 32-bit  
* 甚至其他格式

如果 PC 實際播放裝置是：

> 24-bit / 96kHz

你卻硬要求：

> 16-bit / 48kHz

就需要：

**resampling / format conversion**

否則 WASAPI loopback 開啟可能直接失敗，或者不能按照你預期拿到資料。

### **我建議 M1 改成：**

PC 擷取：

> **取得 Windows 預設輸出裝置實際 loopback format**

然後在 PC 端：

> **統一轉成 48kHz / stereo / S16LE**

最後再傳給 Android。

也就是：

Windows Audio  
     ↓  
WASAPI Loopback  
     ↓  
必要時 Resample / Convert  
     ↓  
48k / Stereo / S16LE  
     ↓  
TCP  
     ↓  
Android AudioTrack

這比現在的設計可靠很多。

---

# **五、USB mDNS 是真的需要測試**

SPEC 自己也把這個列成第一個風險：

> USB 模式下 mDNS 是否能過 RNDIS 介面

這個問題不能單純從理論上回答「一定可以」。

因為：

Android  
  │  
  │ USB  
  ▼  
Windows RNDIS  
  │  
  ├── IP  
  └── multicast / mDNS

IP TCP 能不能通是一件事情。

**mDNS multicast 能不能通是另外一件事情。**

所以我贊成 SPEC 把它列為實機驗證。

不過我會稍微修改 fallback。

目前：

> 掃 /24 TCP connect

這個方法可以，但其實不漂亮。

更簡單的是：

### **USB 模式直接取得 PC 的 RNDIS IP**

例如 PC 顯示：

USB connection detected  
PC IP: 192.168.42.1

Android 直接：

192.168.42.1:58482

這樣甚至不需要 mDNS。

所以 USB 我會設計成：

USB Mode

優先：  
已知/偵測 RNDIS gateway IP → TCP

fallback：  
mDNS

fallback：  
IP scan

甚至可以反過來，直接使用 USB tethering 常見的 gateway 位址。

---

# **六、你真正要的「不限開啟順序」要特別寫進 SPEC**

這個非常重要。

目前 SPEC 有寫：

> 兩端 app 開著、連線成功即自動出聲

但我建議再明確定義成：

### **PC 先開**

PC APP  
 ↓  
TCP Server  
 ↓  
等待手機  
 ↓  
手機 APP 開啟  
 ↓  
Discovery  
 ↓  
Connect  
 ↓  
播放

### **手機先開**

手機 APP  
 ↓  
等待 PC  
 ↓  
PC APP 開啟  
 ↓  
mDNS 出現  
 ↓  
手機自動發現  
 ↓  
Connect  
 ↓  
播放

### **中途斷線**

WiFi/USB/BT 斷線  
 ↓  
停止 AudioTrack / 清理 buffer  
 ↓  
PC 恢復聲音  
 ↓  
持續 Discovery / reconnect  
 ↓  
重新連線  
 ↓  
繼續播放

這才真正符合你的需求。

---

# **七、PC 自動靜音這部分是可行的**

這部分我基本同意 SPEC：

> TCP accept 成功 → 保存 mute/volume → mute  
> disconnect → restore

但是我建議再加一個規則：

### **不要把「TCP connected」直接當成「手機已經開始播放」**

因為：

TCP connected  
↓  
PC mute  
↓  
Android 還沒建立 AudioTrack  
↓  
Android 還沒開始播放

這時可能出現幾百 ms～幾秒的無聲。

更好的方法是增加：

TCP CONNECT  
      ↓  
Android READY  
      ↓  
PC MUTE  
      ↓  
開始送 PCM

也就是增加一個非常簡單的 handshake：

PC → HELLO  
Android → READY  
PC → START AUDIO

這會讓使用體驗好很多。

---

# **八、目前「延遲量測」的方法，我不建議拿來當真正的端到端延遲**

SPEC 寫：

> PC timestamp → Android timestamp → NTP/手動校時 → 相減

這個只能算：

**網路 \+ 接收處理延遲**

而不是完整的：

> PC 聲音實際產生 → 手機喇叭實際發出聲音

因為：

Windows Audio  
 ↓  
WASAPI  
 ↓  
capture buffer  
 ↓  
TCP  
 ↓  
Android socket  
 ↓  
AudioTrack buffer  
 ↓  
Audio hardware  
 ↓  
Speaker

你 timestamp 放在：

PC send

和：

Android AudioTrack.write

中間，沒有包含真正的 speaker output latency。

所以我建議 GUI 不要寫：

> End-to-end latency: 25ms

而是：

> Estimated latency: 25–60ms

或者：

> Network / Buffer latency

真正的 E2E latency 可以之後用：

**PC 播放 click → 手機麥克風錄音 → 比對 waveform**

來測。

---

# **九、Bluetooth 部分，我反而認為是目前最大的不確定因素**

SPEC：

> BT PAN（M2）：手機開藍牙網路共享，PC 加入該 PAN，之後複用同一套 TCP \+ mDNS

這個概念是：

Bluetooth  
   ↓  
PAN  
   ↓  
IP Network  
   ↓  
TCP  
   ↓  
Android Speaker

這和一般：

PC Bluetooth Audio  
   ↓  
A2DP  
   ↓  
手機

完全不同。

而你的需求是：

> 手機選「當作 speaker」

所以你其實是在做：

**Bluetooth Network Speaker**

而不是：

**Bluetooth Audio Speaker**

這是可以做的，但 Android 端、Windows 端 Bluetooth PAN 的實際支援與操作流程，我不會在沒有實機驗證的情況下直接說「一定可以」。

所以 M2 把它獨立出來是正確的。

---

# **十、SPEC 第 11 節的問題，我建議你這樣回答**

這個其實是你現在最需要回覆 Claude 的地方。

## **1\. USB mDNS**

我建議：

> **需要實機驗證。USB 模式優先使用 RNDIS 網路連線；如果 mDNS 可以正常運作就使用 mDNS。如果 mDNS 不可靠，USB 模式改成直接取得/指定 RNDIS 網段中的 PC IP，不使用 /24 掃描作為主要方案。**

原因是我不喜歡每次 USB 連接都掃 254 個 IP。

---

## **2\. 單一 client**

這個非常簡單：

> **只需要一支手機，不需要多手機。維持單一 client。**

因為你的產品本來就是：

> 一台 PC → 一支手機 → 當 PC Speaker

所以不用浪費時間做 multi-client。

---

## **3\. PC 輸出裝置中途變更**

這個我反而建議：

> **需要支援。**

因為實際使用很常見：

PC  
 ↓  
原本喇叭

插入 HDMI  
 ↓  
Windows 預設輸出變成螢幕

拔掉 HDMI  
 ↓  
又變回喇叭

如果你的程式只在啟動時抓一次：

audio\_capture.py

那使用者一換輸出裝置，可能就出問題。

所以我會把這個列為 **M1 必須處理，而不是 stretch item**。

至少做到：

偵測 Default Audio Device 改變  
↓  
停止舊 loopback  
↓  
抓新 Default Device  
↓  
重新建立 capture  
↓  
繼續送手機

這對「真的拿來每天使用」很重要。

---

## **4\. Windows Firewall**

同意：

> **維持正常 Windows Firewall 流程，不繞過。**

第一次出現：

> Allow access

讓使用者允許 Private Network 即可。

---

## **5\. adb reverse**

我的建議：

> **M1 不需要。**

因為你的產品不是 Android 開發工具。

正式使用情境不應該要求：

USB Debugging  
ADB  
Android SDK

所以這個 fallback 對一般使用者沒有意義。

甚至我會把：

> adb reverse fallback

從產品 SPEC 裡刪掉，或者放到：

**Developer / Debugging only**

---

# **十一、我還會增加一個 SPEC 沒有明確處理的問題**

## **Android App 被系統殺掉**

現在寫：

> foreground service \+ mediaPlayback

方向正確。

但需要確保：

手機鎖屏  
↓  
App 還在

螢幕關閉  
↓  
Speaker 繼續播放

切換其他 App  
↓  
Speaker 繼續播放

這是手機當喇叭的基本需求。

另外 Android 新版本的 foreground service / notification 權限與啟動限制，也需要在實作時針對 target SDK 處理。

---

# **十二、還有一個我很建議加入：音訊 buffer 不要「完全沒有 queue」**

SPEC 說：

> 不落地、不排隊、不轉檔

「不要大量 queue」我是同意的。

但：

**完全沒有 ring buffer 並不是低延遲最佳解。**

實際網路會有 jitter：

20ms  
20ms  
35ms  
15ms  
20ms  
40ms

如果：

TCP → AudioTrack

完全一包一包硬送，某一包晚到就可能：

> underrun → 爆音 / 卡頓

所以 SPEC 後面其實已經有：

> ring buffer（最小）

我反而贊成這個。

例如只保留：

**40～100ms 左右的 PCM buffer**

而不是：

> 完全零 buffer

這會比較穩。

---

# **十三、我會把整個 M1 改成這個架構**

                ┌──────────────┐  
                 │ Windows PC   │  
                 │              │  
                 │ System Audio │  
                 └──────┬───────┘  
                        │  
                  WASAPI Loopback  
                        │  
                        ▼  
                Format Conversion  
                 48k/2ch/S16LE  
                        │  
                        ▼  
                  20ms PCM chunk  
                        │  
                        ▼  
                  TCP Server  
                   :58482  
                        │  
            ┌───────────┼───────────┐  
            │           │           │  
           WiFi        USB        BT(M2)  
            │           │           │  
          mDNS        RNDIS        PAN  
            │           │           │  
            └───────────┼───────────┘  
                        │  
                        ▼  
                Android TCP Client  
                        │  
                        ▼  
                  Small Ring Buffer  
                        │  
                        ▼  
                    AudioTrack  
                        │  
                        ▼  
                  Phone Speaker

這個架構是合理的。

---

# **最後：我建議你不要直接回 `ok`**

如果這份 SPEC 是要交給 Claude Code 開始實作，我會先要求它把幾個地方修改掉，再 `ok`。

### **你可以直接把下面這段回給它：**

> **第 11 節決定如下：**

> 1. USB mDNS：需要實機驗證。USB 模式以 RNDIS TCP 連線為主；若 mDNS 在 RNDIS 上可靠則使用，否則改為直接取得/指定 RNDIS 網段中的 PC IP。/24 IP scan 不作為主要方案。  
> 2. 單一 client：確認只支援一支手機，同時只允許一個 Android client。  
> 3. PC 輸出裝置變更：列為 M1 必須支援。Windows 預設輸出裝置變更時，PC 應重新建立 WASAPI loopback capture，讓手機 Speaker 持續工作。  
> 4. Windows Firewall：維持正常 Windows Firewall permission 流程，不繞過。  
> 5. adb reverse：M1 不需要，移至 Developer/Debugging only，不作為一般使用者的 USB fallback。

> **另外請先修改 SPEC 再開始寫程式：**

> * USB 模式需明確標示目前採用 USB Tethering/RNDIS，而不是 USB Audio。  
> * 保留「手機 App / PC App 不限開啟順序」為正式驗收條件，兩端都必須具備自動等待、探索、連線與 reconnect。  
> * PC 音訊擷取不要假設 Windows 預設輸出裝置一定是 48kHz/2ch/S16LE；應從 WASAPI 取得實際格式，必要時轉換成 48kHz/2ch/S16LE 再傳送。  
> * TCP 建立後增加簡單 READY/START handshake，避免 PC 在 Android 尚未準備好 AudioTrack 時就先靜音。  
> * Android 保留小型 ring buffer，避免 WiFi/USB jitter 導致 AudioTrack underrun；不要做大量 queue。  
> * PC 預設輸出裝置切換時重新建立 capture。  
> * 延遲顯示請標示為 estimated/network+buffer latency，不要稱為真正的 end-to-end latency。  
> * M2 Bluetooth PAN 先保留架構，不要在 M1 實作。

> **完成上述 SPEC 修正後，我再回覆 ok 開始實作。**

### **我的整體評價**

**這份 SPEC 不是不能做，反而基本架構抓得很好。**  
但現在比較像「第一次技術設計稿」，還有幾個地方是從「理論上可以」往「真的拿手機、Windows 電腦每天使用也穩定」跨過去時需要修正的。

其中我認為最重要的三個是：

**① USB Tethering 要講清楚**  
**② Windows Audio 格式不能硬寫死 48k/16bit**  
**③ Default Audio Device 中途切換應列 M1 必做**

這三個先修掉，我才會比較放心讓 Claude 開始寫。

手機先開「USB 網路共享」 \<= 有辦法不需要「USB 網路共享」，接上USB就可使用嗎? 四、但「固定 48k/2ch/S16LE」我建議修改 \<= 我建議PC傳出啥，手機端就輸出啥，不確認、不比對、不轉檔，低延遲最重要\! PC 播放 click → 手機麥克風錄音 → 比對 waveform \<= 我不可能去比對waveform，我直接看影片確認就好。 我需要的是Bluetooth/Wifi/USB Audio Speaker 

對，這樣我就完全理解你的真正目標了。你不是要做「USB 網路共享版的手機喇叭」，而是要做：

> **PhoneSpeaker \= 把 Android 手機本身變成 PC 的 Audio Speaker，傳輸介面可以是 USB / WiFi / Bluetooth，而且三種模式都要盡可能直接傳送 PC 原始音訊，優先低延遲。**

這會讓目前 SPEC 的方向需要**重新調整**，尤其 USB。

---

## **1\. USB：可以不開「USB 網路共享」，但要換架構**

答案是：

### **可以，而且如果你的目標真的是 USB Audio Speaker，我反而不建議用 USB Tethering。**

目前 SPEC 的 USB：

> USB → USB Tethering → RNDIS → IP → TCP → Android

這其實是「USB 網路 Speaker」，不是你要的「USB Audio Speaker」。

你真正要的是：

PC  
 │  
 │ USB Cable  
 ▼  
Android Phone  
 │  
 ▼  
Phone Speaker

也就是 USB 本身傳輸音訊資料。

---

# **2\. 但這裡有一個很重要的 Android USB 限制**

Android 官方確實支援 USB Host，Android 5.0+ 也支援部分 USB Audio Class（UAC1）。([Android Developers](https://developer.android.google.cn/develop/connectivity/usb?hl=en&utm_source=chatgpt.com))

但是：

### **PC 並不是一般的 USB Audio「輸出裝置」**

一般 USB Audio 是：

PC  
 │ USB  
 ▼  
USB DAC / USB Speaker

PC 把 USB 裝置當成：

> 「這是一個 USB Audio Device」

然後 Windows Audio 可以直接把音訊送進去。

但你的手機如果只是：

Android App

插進 PC USB，

**不能只靠 Android App 就讓 Windows 自動把手機認成標準 USB Speaker。**

你需要讓手機在 USB 上**呈現一個 Windows 可以使用的 USB Audio Device**，或者採用另一種自訂 USB 通訊協定。

Android 官方的 USB accessory / host 模式，本身就有這方面的限制；Accessory 模式的官方 USB Audio 支援主要是 **Android → USB host** 的音訊方向，並不是你現在要的 PC → Android Speaker。([Android Open Source Project](https://source.android.com/docs/core/audio/usb?utm_source=chatgpt.com))

---

# **3\. 所以 USB 有兩條路**

### **A. 自訂 USB protocol**

Windows App  
   ↓  
Windows USB driver / WinUSB  
   ↓  
USB  
   ↓  
Android USB Host API  
   ↓  
AudioTrack  
   ↓  
Phone Speaker

優點：

* 不需要 USB tethering  
* 不需要 IP  
* 不需要 TCP  
* 延遲可以非常低  
* 完全符合你的「USB Speaker」概念

缺點：

**Windows 端不能只用 Python socket。**

需要處理 USB device / interface / endpoint，Windows 端可能需要 WinUSB/libusb 等方式。

---

### **B. 讓手機真的偽裝成 USB Audio Device**

也就是：

Windows  
   ↓  
Windows Audio  
   ↓  
USB Audio Driver  
   ↓  
USB  
   ↓  
Android  
   ↓  
Speaker

這才是最漂亮的：

> **插 USB → Windows 直接看到一個 Speaker**

但這就不是單純 Android App \+ Python 可以很容易做到的事情。

需要 Android USB device/gadget 層面的支援，而且不同手機 SoC、kernel、ROM 支援程度可能差很多。

所以如果你要求：

> **任何 Android 手機插上去，Windows 不裝 driver，直接把手機當 USB Speaker**

這個目標會比 WiFi 版本困難很多。

---

# **4\. WiFi 就非常適合你**

WiFi 可以維持現在 SPEC：

PC Audio  
 ↓  
WASAPI  
 ↓  
PCM  
 ↓  
TCP  
 ↓  
Android  
 ↓  
AudioTrack  
 ↓  
Speaker

這個沒問題。

而且你要求：

> PC App / Phone App 誰先開都沒關係

也可以做到。

---

# **5\. Bluetooth 也要重新定義**

你現在 SPEC 寫的是：

> Bluetooth PAN → TCP

但你現在明確告訴我：

> **我要 Bluetooth Audio Speaker**

那我認為這個方向也應該重新研究。

因為你要的其實是：

PC  
 ↓  
Bluetooth  
 ↓  
Android Phone  
 ↓  
Phone Speaker

而不是：

PC  
 ↓  
Bluetooth PAN  
 ↓  
TCP  
 ↓  
Android

這兩個完全不同。

---

# **6\. 你的「PC 傳什麼，手機就播什麼」我同意**

這一點我收回前面的建議。

你的優先級是：

> **LOW LATENCY \> 相容性 / 格式自動轉換**

那就不要在 PC 端做：

detect format  
 ↓  
resample  
 ↓  
convert

而是：

PC WASAPI Loopback  
        ↓  
拿到什麼 format  
        ↓  
原封不動傳  
        ↓  
Android  
        ↓  
用相同 format 播放

例如 PC 是：

44.1kHz  
16bit  
Stereo

就傳：

44.1kHz / 16bit / Stereo

PC 是：

48kHz  
24bit  
Stereo

就傳：

48kHz / 24bit / Stereo

**不轉換。**

---

# **7\. 但要注意：這不是「完全不確認」**

這裡我要幫你把概念講得更精確。

你不要：

> **PC → Android 比對 → 轉成另一個格式**

我同意。

但是 Android 的 AudioTrack 還是需要知道：

sample rate  
channel count  
encoding

不然它不知道怎麼解讀 PCM。

所以最佳方案不是：

> 不確認格式

而是：

### **PC 告訴 Android：「這次資料就是這個格式」，Android 照這個格式播放。**

例如連線建立：

PC → FORMAT  
       48000  
       stereo  
       PCM\_16

Android → READY

PC → PCM PCM PCM PCM...

而不是：

PC  
 ↓  
48k conversion  
 ↓  
Android

這樣**沒有 resampling，也沒有轉檔**。

只做 metadata 傳遞。

---

# **8\. 甚至你的封包格式也應該改**

目前 SPEC 把格式寫死：

> 48000 Hz / 2ch / S16LE

如果按照你現在的要求，我會改成：

Connection Handshake

sample\_rate  
channels  
bits / encoding

然後後面：

PCM data  
PCM data  
PCM data  
PCM data

音訊本身完全不修改。

---

# **9\. 你說「我直接看影片確認就好」——完全可以**

對這個專案，我也不認為你需要搞什麼：

> NTP  
> timestamp  
> waveform  
> microphone recording  
> mathematical E2E measurement

目前 SPEC 那一整套：

對你這個專案來說有點過度工程。

你的驗收方式可以非常簡單：

### **播放一段有明顯節奏的影片**

例如：

PC 播放 YouTube  
       ↓  
手機 Speaker  
       ↓  
用另一台手機錄影

直接看：

* 有沒有聲音  
* 聲音有沒有中斷  
* 延遲是否可以接受  
* USB / WiFi / BT 哪個最快  
* 斷線是否恢復  
* App 誰先開是否都可以

這就足夠作為 **M1/M2 實際使用驗收**。

---

# **10\. 所以我現在會重新定義你的專案**

不是：

> **TCP Phone Speaker**

而是：

# **PhoneSpeaker**

### **USB**

**USB Audio / USB direct streaming**

PC ←→ USB ←→ Android

### **WiFi**

**WiFi direct streaming**

PC ←→ WiFi ←→ Android

### **Bluetooth**

**Bluetooth Audio / direct streaming**

PC ←→ Bluetooth ←→ Android

三者最後都進：

Android  
   ↓  
AudioTrack  
   ↓  
Phone Speaker

---

# **11\. 這也代表目前 SPEC 第 2 節要改**

現在寫：

> USB：手機開 USB 網路共享

這個應該刪掉。

你真正要的應該是：

USB:  
USB cable 連接 PC 與手機  
手機 App / PC App 啟動  
自動建立 USB 音訊傳輸  
手機 Speaker 播放  
不需要 USB 網路共享

WiFi:  
同一 WiFi  
手機 App / PC App 啟動  
自動探索與連線  
手機 Speaker 播放

Bluetooth:  
PC / 手機 Bluetooth 配對  
手機 App 選擇 Speaker  
建立 Bluetooth 音訊傳輸  
手機 Speaker 播放

---

# **12\. 我現在最想先確認的其實是 USB**

因為你的需求如果是：

> **USB 一插就把 Android 當成 Windows 的「真正 Speaker」**

那我不建議 Claude 直接照目前 SPEC 開始寫。

我們應該先確認：

**你的目標 Android 手機，是否允許 App/系統把手機 USB 端呈現成 Windows 可識別的 USB Audio Device。**

如果不能，那就要走：

> **自訂 USB protocol \+ Windows USB driver/WinUSB**

這仍然可以做到你要的：

> 插 USB → App → 手機播聲音

只是 PC 端不是把手機當「標準 Windows Speaker」，而是 PhoneSpeaker PC App 自己把 WASAPI 音訊送進 USB。

---

## **最重要的一點**

你現在的需求我理解成：

> **我要的是「手機當喇叭」，USB/WiFi/Bluetooth 只是三種傳輸管道；不是我要把三種管道都做成 TCP。**

這個理解才對。

而且在這個前提下，我會建議**先不要讓 Claude 開始寫目前這份 SPEC**。

目前 SPEC 的：

**USB \= RNDIS/Tethering**  
**BT \= PAN**

都跟你現在真正要的 **USB Audio / Bluetooth Audio Speaker** 有偏差。

如果你願意，我下一步可以直接幫你把這份 `SPEC.md` **重新改成符合你現在這個真正需求的版本**，並且把「USB 到底要用 UAC 還是自訂 USB protocol」、「Bluetooth 到底能不能讓 Android 當 Speaker」這兩個最關鍵的技術路線先查清楚，再給 Claude 實作。

