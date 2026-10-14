#[cfg(not(test))]
const SERVICE_NAME: &str = "com.kcode.app";
#[cfg(not(test))]
const LEGACY_SERVICE_NAME: &str = "com.kcoder.app";
#[cfg(not(test))]
const LEGACY_API_KEY_ACCOUNT: &str = "default-provider-api-key";

pub trait CredentialStore: Send + Sync {
    fn get_api_key(&self, provider_id: &str) -> Result<Option<String>, CredentialError>;
    fn set_api_key(&self, provider_id: &str, api_key: &str) -> Result<(), CredentialError>;
    fn delete_api_key(&self, provider_id: &str) -> Result<(), CredentialError>;
}

#[derive(Debug, Clone, thiserror::Error, PartialEq, Eq)]
pub enum CredentialError {
    #[error("API key is empty")]
    Empty,
    #[error("operating system credential store failed: {0}")]
    Unavailable(String),
}

#[derive(Debug, Default)]
pub struct OsCredentialStore {
    #[cfg(not(test))]
    access_lock: std::sync::Mutex<()>,
}

impl OsCredentialStore {
    pub fn new() -> Self {
        Self::default()
    }

    #[cfg(not(test))]
    fn entry(&self, account: &str) -> Result<keyring::Entry, CredentialError> {
        Self::entry_for_service(SERVICE_NAME, account)
    }

    #[cfg(not(test))]
    fn entry_for_service(service: &str, account: &str) -> Result<keyring::Entry, CredentialError> {
        keyring::Entry::new(service, account)
            .map_err(|error| CredentialError::Unavailable(error.to_string()))
    }

    #[cfg(not(test))]
    fn account(provider_id: &str) -> String {
        format!("provider-api-key:{provider_id}")
    }

    #[cfg(not(test))]
    fn read_entry(&self, account: &str) -> Result<Option<String>, CredentialError> {
        self.read_entry_for_service(SERVICE_NAME, account)
    }

    #[cfg(not(test))]
    fn read_entry_for_service(
        &self,
        service: &str,
        account: &str,
    ) -> Result<Option<String>, CredentialError> {
        match Self::entry_for_service(service, account)?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(CredentialError::Unavailable(error.to_string())),
        }
    }

    #[cfg(not(test))]
    fn delete_entry(&self, account: &str) -> Result<(), CredentialError> {
        match self.entry(account)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(CredentialError::Unavailable(error.to_string())),
        }
    }
}

#[cfg(not(test))]
impl CredentialStore for OsCredentialStore {
    fn get_api_key(&self, provider_id: &str) -> Result<Option<String>, CredentialError> {
        let _guard = self.access_lock.lock().map_err(|_| {
            CredentialError::Unavailable("credential lock was poisoned".to_string())
        })?;
        let credential = self.read_entry(&Self::account(provider_id))?;
        if let Some(value) = credential {
            return Ok(Some(value));
        }
        if provider_id == "default" {
            if let Some(value) = self.read_entry(LEGACY_API_KEY_ACCOUNT)? {
                return Ok(Some(value));
            }
        }

        // The application was renamed from k-coder to KCode. Preserve access to
        // credentials written by the old installation and copy them into the
        // new service on first read. The secret never leaves the OS credential
        // store or appears in the returned provider view.
        let legacy_account = Self::account(provider_id);
        let legacy = self
            .read_entry_for_service(LEGACY_SERVICE_NAME, &legacy_account)?
            .or_else(|| {
                if provider_id == "default" {
                    self.read_entry_for_service(LEGACY_SERVICE_NAME, LEGACY_API_KEY_ACCOUNT)
                        .ok()
                        .flatten()
                } else {
                    None
                }
            });
        if let Some(value) = legacy {
            let _ = self.entry(&legacy_account).and_then(|entry| {
                entry
                    .set_password(&value)
                    .map_err(|error| CredentialError::Unavailable(error.to_string()))
            });
            return Ok(Some(value));
        }
        Ok(None)
    }

    fn set_api_key(&self, provider_id: &str, api_key: &str) -> Result<(), CredentialError> {
        let api_key = api_key.trim();
        if api_key.is_empty() {
            return Err(CredentialError::Empty);
        }
        let _guard = self.access_lock.lock().map_err(|_| {
            CredentialError::Unavailable("credential lock was poisoned".to_string())
        })?;
        self.entry(&Self::account(provider_id))?
            .set_password(api_key)
            .map_err(|error| CredentialError::Unavailable(error.to_string()))
    }

    fn delete_api_key(&self, provider_id: &str) -> Result<(), CredentialError> {
        let _guard = self.access_lock.lock().map_err(|_| {
            CredentialError::Unavailable("credential lock was poisoned".to_string())
        })?;
        self.delete_entry(&Self::account(provider_id))?;
        if provider_id == "default" {
            self.delete_entry(LEGACY_API_KEY_ACCOUNT)?;
        }
        Ok(())
    }
}

#[cfg(test)]
impl CredentialStore for OsCredentialStore {
    fn get_api_key(&self, _provider_id: &str) -> Result<Option<String>, CredentialError> {
        Err(CredentialError::Unavailable(
            "native credential access is disabled in tests".to_string(),
        ))
    }

    fn set_api_key(&self, _provider_id: &str, _api_key: &str) -> Result<(), CredentialError> {
        Err(CredentialError::Unavailable(
            "native credential access is disabled in tests".to_string(),
        ))
    }

    fn delete_api_key(&self, _provider_id: &str) -> Result<(), CredentialError> {
        Err(CredentialError::Unavailable(
            "native credential access is disabled in tests".to_string(),
        ))
    }
}
