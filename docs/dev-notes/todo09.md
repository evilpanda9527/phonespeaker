**Prompt(M1-B / U3 PoC:AOA 自訂 USB — 只評估與回報,先不實作)**

> 現在進入 M1-B 最後一個變體 **U3 =「USB (AOA)」** 的 PoC 階段。依 §14「先 PoC、逐項測試通過才前進」,**本輪只做技術評估與回報,不要寫實作、不要動任何既有檔案**。
>
> **U3 的目標與已知背景:**
> - U3 要達成的使用者價值:USB 線接上後,**手機端連「USB 網路共享」和「USB 偵錯」都不用開**,插上就用(這是它相對 U1/U2 的唯一好處)。
> - 技術路線:**AOA(Android Open Accessory)accessory 模式 + 自訂 USB bulk data channel**。PC 當 USB host,透過 libusb 跟進入 accessory 模式的 Android 通訊,自己傳 PCM。
> - 已知限制(先前確認過):AOA 內建的 audio 功能已在 Android 8 淘汰,所以**不能用 AOA audio,要自刻 bulk data channel**;PC 端需要 **WinUSB 驅動(未簽章,自用可接受)** + libusb,不能只用 Python socket。
> - 環境:PC 是 Windows(這台)、手機是三星 `R5CT311BC2X`(前面 U1/U2 測試用的同一支)。
>
> **請評估並回報以下,不要動手實作:**
> 1. **可行性**:在這台 Windows + 這支三星手機上,AOA accessory 模式實際能不能建立?PC 端要用什麼(libusb-win32 / WinUSB via Zadig / pyusb + libusb backend)?Android 端要怎麼寫(UsbManager accessory API / accessory filter)?
> 2. **驅動負擔**:PC 端到底要裝什麼驅動、怎麼裝(Zadig 手動?還是可程式化 via libwdi/pnputil?)、未簽章警告會出現在哪一步。**這關係到之後 §11 單一安裝檔要怎麼把驅動包進去**,請一併評估驅動能不能在安裝流程裡自動裝。
> 3. **開發複雜度與風險**:相較 U1/U2(複用 TCP),U3 要新寫 USB bulk 通訊,列出主要的技術風險與不確定點(例如:accessory 模式進入時裝置會重新枚舉、Windows 端驅動綁定、bulk 傳輸的頻寬/延遲是否夠 48kHz 立體聲無損 PCM 約 3Mbps)。
> 4. **要新增/修改哪些檔案**(先列規劃,不實作):PC 端 `usb_aoa.py`、Android 端 accessory transport、UI 加選項、`StreamerService.kt` 工廠加 case。
> 5. **你的建議**:以你的評估,U3 值不值得做?有沒有哪個環節(尤其 Windows 驅動 + libusb 這塊)是明顯的坑或 blocker?
>
> **回報後停下,等我確認,再決定是否進入 U3 實作。** 不要在這輪產生實作程式碼。

---