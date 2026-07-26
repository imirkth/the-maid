// The Maid — Lightning donation support
// User's own node backend via LNURL-pay or direct REST endpoint.
// No third-party payment processor.

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct InvoiceResult {
    pub bolt11: String,
    pub payment_hash: String,
    pub amount_sats: u64,
    pub expires_at: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct LnurlPayResponse {
    pub callback: String,
    pub max_sendable: u64,
    pub min_sendable: u64,
    pub metadata: String,
    pub tag: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct InvoiceResponse {
    pub pr: String,
    pub routes: Option<Vec<serde_json::Value>>,
}

const DEFAULT_MEMO: &str = "Support The Maid";
const MAX_AMOUNT_SATS: u64 = 10_000_000;
const MIN_AMOUNT_SATS: u64 = 1;

/// Validate a Lightning amount in satoshis.
fn validate_amount(amount_sats: u64) -> Result<(), String> {
    if amount_sats < MIN_AMOUNT_SATS {
        return Err(format!("Amount must be at least {} sat", MIN_AMOUNT_SATS));
    }
    if amount_sats > MAX_AMOUNT_SATS {
        return Err(format!(
            "Amount exceeds maximum {} sats",
            MAX_AMOUNT_SATS
        ));
    }
    Ok(())
}

/// Fetch an invoice from a user-configured Lightning node URL.
/// Supports LNURL-pay endpoints (callback + amount query) and simple
/// invoice endpoints that return `{"pr": "..."}`.
pub async fn fetch_lightning_invoice(
    node_url: &str,
    amount_sats: u64,
    memo: &str,
) -> Result<InvoiceResult, String> {
    validate_amount(amount_sats)?;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {}", e))?;

    // Try LNURL-pay callback first: if URL contains `callback` semantics, query
    // `?amount=<msats>`. Many LNURL-pay callbacks also accept a `comment`.
    let msats = amount_sats * 1000;
    let callback_url = format!("{}?amount={}", node_url.trim_end_matches('/'), msats);

    let resp = client
        .get(&callback_url)
        .send()
        .await
        .map_err(|e| format!("Failed to contact Lightning node: {}", e))?;

    if !resp.status().is_success() {
        return Err(format!("Lightning node returned status {}", resp.status()));
    }

    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse node response: {}", e))?;

    let pr = body
        .get("pr")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "Node response missing bolt11 invoice (pr field)".to_string())?
        .to_string();

    // Extract payment_hash if provided, otherwise derive a placeholder from the invoice.
    let payment_hash = body
        .get("payment_hash")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| {
            // LNURL-pay usually doesn't include payment_hash. Use the first 64 hex chars
            // of the bolt11 as a stable identifier for polling. This is not a real hash,
            // but it lets the frontend track the same invoice request.
            pr.chars().take(64).collect()
        });

    Ok(InvoiceResult {
        bolt11: pr,
        payment_hash,
        amount_sats,
        expires_at: body
            .get("expires_at")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
    })
}

/// Tauri command: create a Lightning invoice using the configured node URL.
#[tauri::command]
pub async fn create_lightning_invoice(
    amount_sats: u64,
    memo: Option<String>,
) -> Result<InvoiceResult, String> {
    use crate::settings::Settings;
    let settings = Settings::load()?;
    let node_url = settings
        .lightning_node_url
        .ok_or_else(|| "No Lightning node configured. Add your node URL in Settings > About.".to_string())?;
    let memo = memo.unwrap_or_else(|| DEFAULT_MEMO.to_string());
    fetch_lightning_invoice(&node_url, amount_sats, &memo).await
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
    async fn test_fetch_invoice_missing_pr_field() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"OK"}"#)
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 1000, "memo").await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("missing bolt11"));
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
            .with_body(r#"{"pr":"lnbc10u1p lightning invoice","payment_hash":"abcdef123456"}"#)
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 1000, "Support").await.unwrap();
        assert_eq!(result.amount_sats, 1000);
        assert_eq!(result.bolt11, "lnbc10u1p lightning invoice");
        assert_eq!(result.payment_hash, "abcdef123456");
    }

    #[tokio::test]
    async fn test_fetch_invoice_uses_bolt11_fallback_hash() {
        let mut server = mockito::Server::new_async().await;
        let url = server.url();
        server
            .mock("GET", "/")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"pr":"lnbc1invoiceWithoutHash"}"#)
            .create_async()
            .await;

        let result = fetch_lightning_invoice(&url, 500, "memo").await.unwrap();
        assert_eq!(result.payment_hash, "lnbc1invoiceWithoutHash".chars().take(64).collect::<String>());
    }
}
