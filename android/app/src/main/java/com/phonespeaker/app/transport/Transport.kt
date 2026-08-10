package com.phonespeaker.app.transport

import com.phonespeaker.app.core.Frame

/**
 * Transport.kt — Transport 介面（§4）。
 *
 * 音訊格式、READY 握手、ring buffer、AudioTrack 播放邏輯都不綁死任何
 * transport；每種 transport 只需要實作這裡定義的介面。對應 PC 端
 * pc/transport/base.py，兩邊的介面設計要保持一致（連線建立/中斷/收送 frame）。
 *
 * 依 §10.3：這是所有 transport 共用的抽象介面，屬於穩定層，凍結後改動要走
 * §10.4 回歸流程。
 */
open class TransportException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** connect() 等待中被 requestCancel() 中斷時拋出（非錯誤，屬正常取消）。 */
class TransportCancelledException(message: String) : TransportException(message)

interface Transport {
    /** 給 UI 顯示用的簡短名稱，例如 "WiFi"。 */
    val displayName: String

    val isConnected: Boolean

    /**
     * 建立連線。會阻塞呼叫的執行緒直到連線建立成功、發生錯誤、或被
     * requestCancel() 取消。取消時拋 TransportCancelledException。
     */
    @Throws(TransportException::class)
    fun connect()

    /** 中斷目前連線（若有）。可重複呼叫，不應拋例外。 */
    fun disconnect()

    /** 讓阻塞在 connect() 的呼叫盡快返回。 */
    fun requestCancel()

    /** 送出一個 frame（FORMAT/READY/FORMAT_UNSUPPORTED/PCM 皆透過這裡送出）。 */
    @Throws(TransportException::class)
    fun sendFrame(frame: Frame)

    /** 收一個完整 frame。連線中斷時拋 TransportException。 */
    @Throws(TransportException::class)
    fun recvFrame(): Frame
}
