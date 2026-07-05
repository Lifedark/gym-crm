// Scanner helper - loaded on scan page
function initScanner(elementId, onScan) {
    const html5QrCode = new Html5Qrcode(elementId);

    function onScanSuccess(decodedText, decodedResult) {
        html5QrCode.stop();
        onScan(decodedText);
        setTimeout(() => {
            html5QrCode.start(
                { facingMode: "environment" },
                { fps: 10, qrbox: { width: 250, height: 250 } },
                onScanSuccess
            );
        }, 3000);
    }

    html5QrCode.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 250, height: 250 } },
        onScanSuccess
    ).catch(err => {
        console.error("Camera error:", err);
    });

    return html5QrCode;
}
