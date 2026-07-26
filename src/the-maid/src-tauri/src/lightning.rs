// The Maid — Lightning donation support
// Donations route to the vendor's own Lightning node / LNURL-pay endpoint.
// URL is baked in at compile time; users cannot redirect payments.

use serde::{Deserialize, Serialize};

/// LNURL-pay endpoint baked into the release binary.
/// Set at build time: MAID_DONATION_LNURL=https://your-node.example/lnurl-pay cargo tauri build
const DONATION_LNURL: &str = env!(
    "MAID_DONATION_LNURL",
    "https://PLACEHOLDER.themaid.app/lnurl-pay"
);

const DEFAULT_MEMO: &str = "Support The Maid";
const MAX_AMOUNT_SATS: u64 = 10_000_000;
const MIN_AMOUNT_SATS: u64 = 1;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct InvoiceResult {
    pub bolt11: String,
    pub payment_hash: String,
    pub amount_sats: u64,
    pub verify_url: String,
    pub expires_at: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PaymentStatus {
    pub settled: bool,
    pub preimage: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct CallbackResponse {
    pr: String,
    payment_hash: Option<String>,
    verify: Option<String>,
    expires_at: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct VerifyResponse {
    status: String,
    settled: Option<bool>,
    preimage: Option<String>,
}

/// Validate a Lightning amount in satoshis.
fn validate_amount(amount_sats: u64) -> Result<(), String> {
    if amount_sats < MIN_AMOUNT_SATS {
        return Err(format!("Amount must be at least {} sat", MIN_AMOUNT_SATS));
    }
    if amount_sats > MAX_AMOUNT_SATS {
        return Err(format!("Amount exceeds maximum {} sats", MAX_AMOUNT_SATS));
    }
    Ok(())
}

fn http_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {}", e))
}

/// Fetch an invoice from a LNURL-pay callback URL.
/// The configured URL is treated as the callback; we call `callback?amount=<msats>`.
pub async fn fetch_lightning_invoice(
    callback_url: &str,
    amount_sats: u64,
    _memo: &str,
) -> Result<InvoiceResult, String> {
    validate_amount(amount_sats)?;

    let client = http_client()?;
    let msats = amount_sats * 1000;
    let url = format!("{}?amount={}", callback_url.trim_end_matches('/'), msats);

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Failed to contact Lightning node: {}", e))?;

    if !resp.status().is_success() {
        return Err(format!("Lightning node returned status {}", resp.status()));
    }

    let body: CallbackResponse = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse node response: {}", e))?;

    let verify_url = body
        .verify
        .ok_or_else(|| "LNURL-pay response missing verify URL".to_string())?;

    let payment_hash = body
        .payment_hash
        .unwrap_or_else(|| body.pr.chars().take(64).collect());

    Ok(InvoiceResult {
        bolt11: body.pr,
        payment_hash,
        amount_sats,
        verify_url,
        expires_at: body.expires_at,
    })
}

/// Poll the LNURL-verify URL to check if the invoice has been paid.
pub async fn verify_lightning_payment(verify_url: &str) -> Result<PaymentStatus, String> {
    let client = http_client()?;
    let resp = client
        .get(verify_url)
        .send()
        .await
        .map_err(|e| format!("Failed to contact verify endpoint: {}", e))?;

    if !resp.status().is_success() {
        return Err(format!("Verify endpoint returned status {}", resp.status()));
    }

    let body: VerifyResponse = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse verify response: {}", e))?;

    if body.status != "OK" {
        return Ok(PaymentStatus {
            settled: false,
            preimage: None,
        });
    }

    let settled = body.settled.unwrap_or(false);
    let preimage = body.preimage.filter(|p| !p.is_empty());

    Ok(PaymentStatus {
        settled: settled && preimage.is_some(),
        preimage,
    })
}

/// Tauri command: create a Lightning invoice using the vendor's configured node.
#[tauri::command]
pub async fn create_lightning_invoice(
    amount_sats: u64,
    memo: Option<String>,
) -> Result<InvoiceResult, String> {
    let _memo = memo.unwrap_or_else(|| DEFAULT_MEMO.to_string());
    if DONATION_LNURL.contains("PLACEHOLDER") {
        return Err("Donation endpoint not configured in this build".to_string());
    }
    fetch_lightning_invoice(DONATION_LNURL, amount_sats, &_memo).await
}

/// Tauri command: poll the LNURL-verify URL and return payment status.
#[tauri::command]
pub async fn verify_lightning_payment_cmd(verify_url: String) -> Result<PaymentStatus, String> {
    verify_lightning_payment(&verify_url).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_amount_rejects_zero() {
        let err = validate_amount(0).unwrap_err();
        assert!(err.contains("at least"));
    }

    #[test]
    fn test_validate_amount_rejects_too_large() {
        let err = validate_amount(MAX_AMOUNT_SATS + 1).unwrap_err();
        assert!(err.contains("exceeds maximum"));
    }

    #[test]
    fn test_validate_amount_accepts_one_sat() {
        assert!(validate_amount(1).is_ok());
    }

    #[test]
    fn test_validate_amount_accepts_max() {
        assert!(validate_amount(MAX_AMOUNT_SATS).is_ok());
    }

    #[tokio::test]
    async fn test_fetch_invoice_missing_verify_url() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"pr":"lnbc10u1p invoice"}"#)
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 1000, "memo").await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("missing verify URL"));
    }

    #[tokio::test]
    async fn test_fetch_invoice_returns_invoice_result() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .match_query(mockito::Matcher::UrlEncoded("amount".into(), "1000000".into()))
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"pr":"lnbc10u1p lightning invoice","payment_hash":"abcdef123456","verify":"https://example.com/verify/1","expires_at":"2026-12-31T23:59:59Z"}"#)
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 1000, "Support")
            .await
            .unwrap();
        assert_eq!(result.amount_sats, 1000);
        assert_eq!(result.bolt11, "lnbc10u1p lightning invoice");
        assert_eq!(result.payment_hash, "abcdef123456");
        assert_eq!(result.verify_url, "https://example.com/verify/1");
        assert_eq!(result.expires_at, Some("2026-12-31T23:59:59Z".to_string()));
    }

    #[tokio::test]
    async fn test_fetch_invoice_uses_bolt11_fallback_hash() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(
                r#"{"pr":"lnbc1invoiceWithoutHash","verify":"https://example.com/verify/2"}"#,
            )
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 500, "memo").await.unwrap();
        assert_eq!(
            result.payment_hash,
            "lnbc1invoiceWithoutHash"
                .chars()
                .take(64)
                .collect::<String>()
        );
        assert_eq!(result.verify_url, "https://example.com/verify/2");
    }

    #[tokio::test]
    async fn test_verify_payment_settled_with_preimage() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"OK","settled":true,"preimage":"abcdef123456"}"#)
            .create_async()
            .await;

        let result = verify_lightning_payment(&url).await.unwrap();
        assert!(result.settled);
        assert_eq!(result.preimage, Some("abcdef123456".to_string()));
    }

    #[tokio::test]
    async fn test_verify_payment_not_settled() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"OK","settled":false,"preimage":null}"#)
            .create_async()
            .await;

        let result = verify_lightning_payment(&url).await.unwrap();
        assert!(!result.settled);
        assert!(result.preimage.is_none());
    }

    #[tokio::test]
    async fn test_verify_payment_missing_preimage_not_settled() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"OK","settled":true,"preimage":""}"#)
            .create_async()
            .await;

        let result = verify_lightning_payment(&url).await.unwrap();
        assert!(!result.settled);
        assert!(result.preimage.is_none());
    }

    #[tokio::test]
    async fn test_create_lightning_invoice_rejects_placeholder_url() {
        let result = create_lightning_invoice(1000, Some("memo".to_string())).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("not configured"));
    }

    #[tokio::test]
    async fn test_verify_payment_status_not_ok_returns_unsettled() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"ERROR","settled":false,"preimage":null}"#)
            .create_async()
            .await;

        let result = verify_lightning_payment(&url).await.unwrap();
        assert!(!result.settled);
        assert!(result.preimage.is_none());
    }

    #[test]
    fn test_invoice_result_serialization_roundtrip() {
        let invoice = InvoiceResult {
            bolt11: "lnbc10u1p test".to_string(),
            payment_hash: "abcdef".to_string(),
            amount_sats: 1000,
            verify_url: "https://example.com/verify".to_string(),
            expires_at: Some("2026-12-31T23:59:59Z".to_string()),
        };
        let json = serde_json::to_string(&invoice).unwrap();
        let back: InvoiceResult = serde_json::from_str(&json).unwrap();
        assert_eq!(back.bolt11, invoice.bolt11);
        assert_eq!(back.verify_url, invoice.verify_url);
    }

    #[test]
    fn test_payment_status_serialization_roundtrip() {
        let status = PaymentStatus {
            settled: true,
            preimage: Some("preimage123".to_string()),
        };
        let json = serde_json::to_string(&status).unwrap();
        let back: PaymentStatus = serde_json::from_str(&json).unwrap();
        assert!(back.settled);
        assert_eq!(back.preimage, Some("preimage123".to_string()));
    }
}
