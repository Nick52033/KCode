use uuid::Uuid;

use crate::protocol::{ChatMessage, ContentBlock, ImageAttachment, MessageRole, PROTOCOL_VERSION};
use crate::providers::{ProviderImage, ProviderMessage};
use crate::storage::now_ms;

use super::AgentRuntimeError;

const MAX_INPUT_BYTES: usize = 100_000;
const DOCUMENT_ATTACHMENT_PREFIX: &str = "\u{001e}KCODE_DOCUMENT_ATTACHMENT_V1:";
const MAX_IMAGE_COUNT: usize = 4;
const MAX_IMAGE_BYTES: usize = 4 * 1024 * 1024;
const MAX_TOTAL_IMAGE_BYTES: usize = 8 * 1024 * 1024;

pub(super) fn user_message(
    text: String,
    attachments: Vec<ImageAttachment>,
    _supports_vision: bool,
) -> Result<ChatMessage, AgentRuntimeError> {
    if attachments.len() > MAX_IMAGE_COUNT {
        return Err(AgentRuntimeError::InvalidInput(format!(
            "at most {MAX_IMAGE_COUNT} images may be attached"
        )));
    }
    let mut total = 0usize;
    let (text, document_contexts) = split_document_attachments(&text)?;
    let mut content = if text.is_empty() && attachments.is_empty() {
        vec![ContentBlock::Context {
            text: "请分析用户提供的图片。".into(),
        }]
    } else if text.is_empty() {
        Vec::new()
    } else {
        vec![ContentBlock::Text { text }]
    };
    content.extend(
        document_contexts
            .into_iter()
            .map(|(name, text)| ContentBlock::Context {
                text: format!("[附件: {name}]\n{text}"),
            }),
    );
    for attachment in attachments {
        let name: String = attachment.name.chars().take(255).collect();
        let (_, encoded) = parse_image_data_url(&attachment.data_url)?;
        let decoded = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, encoded)
            .map_err(|_| {
            AgentRuntimeError::InvalidInput("image data is not valid base64".into())
        })?;
        if decoded.len() > MAX_IMAGE_BYTES {
            return Err(AgentRuntimeError::InvalidInput(
                "an attached image exceeds the 4 MiB limit".into(),
            ));
        }
        total = total.saturating_add(decoded.len());
        if total > MAX_TOTAL_IMAGE_BYTES {
            return Err(AgentRuntimeError::InvalidInput(
                "attached images exceed the 8 MiB total limit".into(),
            ));
        }
        content.push(ContentBlock::Image {
            name,
            data_url: attachment.data_url,
        });
    }
    Ok(ChatMessage {
        schema_version: PROTOCOL_VERSION,
        id: Uuid::new_v4().to_string(),
        role: MessageRole::User,
        content,
        created_at_ms: now_ms(),
    })
}

#[derive(serde::Deserialize)]
struct DocumentAttachmentEnvelope {
    name: String,
    content: String,
}

/// Pull document payloads out of the transport string into non-visible context blocks.
/// The prefix is deliberately private to the desktop client and each envelope is one
/// JSON line, so arbitrary document newlines cannot be mistaken for another attachment.
fn split_document_attachments(
    input: &str,
) -> Result<(String, Vec<(String, String)>), AgentRuntimeError> {
    let mut visible = String::new();
    let mut contexts = Vec::new();
    for line in input.split('\n') {
        if let Some(payload) = line.strip_prefix(DOCUMENT_ATTACHMENT_PREFIX) {
            let envelope: DocumentAttachmentEnvelope =
                serde_json::from_str(payload).map_err(|_| {
                    AgentRuntimeError::InvalidInput("document attachment is not valid".into())
                })?;
            let name: String = envelope.name.chars().take(255).collect();
            if name.trim().is_empty() {
                return Err(AgentRuntimeError::InvalidInput(
                    "document attachment name must not be empty".into(),
                ));
            }
            contexts.push((name, envelope.content));
        } else {
            if !visible.is_empty() {
                visible.push('\n');
            }
            visible.push_str(line);
        }
    }
    Ok((visible.trim().to_string(), contexts))
}

pub(crate) fn build_user_message(
    input: &str,
    attachments: Vec<ImageAttachment>,
    supports_vision: bool,
) -> Result<ChatMessage, AgentRuntimeError> {
    let input = validate_input(input, !attachments.is_empty())?;
    user_message(input, attachments, supports_vision)
}

pub(super) fn truncate_utf8(value: &str, max_bytes: usize) -> &str {
    if value.len() <= max_bytes {
        return value;
    }
    let mut end = max_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    &value[..end]
}

fn parse_image_data_url(value: &str) -> Result<(&str, &str), AgentRuntimeError> {
    let (metadata, encoded) = value.split_once(',').ok_or_else(|| {
        AgentRuntimeError::InvalidInput("image attachment must be a data URL".into())
    })?;
    let media_type = metadata
        .strip_prefix("data:")
        .and_then(|value| value.strip_suffix(";base64"))
        .ok_or_else(|| AgentRuntimeError::InvalidInput("image data URL must use base64".into()))?;
    if !matches!(
        media_type,
        "image/png" | "image/jpeg" | "image/gif" | "image/webp"
    ) {
        return Err(AgentRuntimeError::InvalidInput(
            "image type must be PNG, JPEG, GIF, or WebP".into(),
        ));
    }
    Ok((media_type, encoded))
}

pub(super) fn chat_to_provider(
    message: ChatMessage,
    supports_vision: bool,
) -> Option<ProviderMessage> {
    let text = message.text();
    let images = message
        .content
        .into_iter()
        .filter_map(|block| match block {
            ContentBlock::Image { name, data_url } if supports_vision => {
                Some(ProviderImage { name, data_url })
            }
            ContentBlock::Image { .. } => None,
            ContentBlock::Text { .. } | ContentBlock::Context { .. } => None,
        })
        .collect::<Vec<_>>();
    match (message.role, images.is_empty()) {
        (MessageRole::User, false) => Some(ProviderMessage::UserContent { text, images }),
        (MessageRole::Assistant, false) => {
            Some(ProviderMessage::AssistantImageReference { text, images })
        }
        (role, _) => Some(ProviderMessage::Text { role, text }),
    }
}

fn validate_input(input: &str, allow_empty: bool) -> Result<String, AgentRuntimeError> {
    let input = input.trim();
    if input.is_empty() && !allow_empty {
        return Err(AgentRuntimeError::InvalidInput(
            "input must not be empty".to_string(),
        ));
    }
    if input.len() > MAX_INPUT_BYTES {
        return Err(AgentRuntimeError::InvalidInput(format!(
            "input exceeds the {MAX_INPUT_BYTES} byte limit"
        )));
    }
    Ok(input.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn document_attachments_are_context_and_not_visible_text() {
        let input = format!(
            "用户说明\n{DOCUMENT_ATTACHMENT_PREFIX}{}",
            serde_json::json!({"name": "说明.txt", "content": "第一行\n第二行"})
        );
        let message = user_message(input, Vec::new(), false).unwrap();
        assert_eq!(message.visible_text(), "用户说明");
        assert_eq!(message.text(), "用户说明[附件: 说明.txt]\n第一行\n第二行");
        assert!(matches!(message.content[1], ContentBlock::Context { .. }));
    }

    #[test]
    fn assistant_generated_images_become_reference_inputs_for_vision_providers() {
        let message = ChatMessage {
            schema_version: PROTOCOL_VERSION,
            id: "assistant-image".into(),
            role: MessageRole::Assistant,
            content: vec![
                ContentBlock::Text {
                    text: "已生成一张图片。".into(),
                },
                ContentBlock::Image {
                    name: "generated.png".into(),
                    data_url: "data:image/png;base64,AA==".into(),
                },
            ],
            created_at_ms: 1,
        };

        assert!(matches!(
            chat_to_provider(message.clone(), true),
            Some(ProviderMessage::AssistantImageReference { text, images })
                if text == "已生成一张图片。"
                    && images.len() == 1
                    && images[0].data_url == "data:image/png;base64,AA=="
        ));
        assert!(matches!(
            chat_to_provider(message, false),
            Some(ProviderMessage::Text { role: MessageRole::Assistant, text })
                if text == "已生成一张图片。"
        ));
    }
}
