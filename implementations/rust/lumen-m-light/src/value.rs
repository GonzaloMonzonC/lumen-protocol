use serde::{Deserialize, Serialize};
use std::cmp::Ordering;

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum Value {
    #[default]
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<Value>),
    Object(serde_json::Map<String, serde_json::Value>),
}

impl Value {
    pub fn number(value: impl Into<f64>) -> Self {
        Self::Number(value.into())
    }

    pub fn as_number(&self) -> f64 {
        match self {
            Self::Number(v) => *v,
            Self::Bool(v) => u8::from(*v) as f64,
            Self::String(v) => v.trim().parse::<f64>().unwrap_or(0.0),
            _ => 0.0,
        }
    }

    pub fn as_string(&self) -> String {
        match self {
            Self::Null => String::new(),
            Self::Bool(v) => if *v { "1" } else { "0" }.to_string(),
            Self::Number(v) if v.fract() == 0.0 && v.abs() < 9.0e15 => {
                format!("{}", *v as i64)
            }
            Self::Number(v) => format!("{v}"),
            Self::String(v) => v.clone(),
            Self::Array(v) => serde_json::to_string(v).unwrap_or_default(),
            Self::Object(v) => serde_json::to_string(v).unwrap_or_default(),
        }
    }

    pub fn truthy(&self) -> bool {
        match self {
            Self::Null => false,
            Self::Bool(v) => *v,
            Self::Number(v) => *v != 0.0 && !v.is_nan(),
            Self::String(v) => !v.is_empty() && v.parse::<f64>() != Ok(0.0),
            Self::Array(v) => !v.is_empty(),
            Self::Object(v) => !v.is_empty(),
        }
    }

    pub fn normalized(self) -> Self {
        match self {
            Self::Number(-0.0) => Self::Number(0.0),
            other => other,
        }
    }

    pub fn from_json(value: serde_json::Value) -> Self {
        match value {
            serde_json::Value::Null => Self::Null,
            serde_json::Value::Bool(v) => Self::Bool(v),
            serde_json::Value::Number(v) => Self::Number(v.as_f64().unwrap_or(0.0)),
            serde_json::Value::String(v) => Self::String(v),
            serde_json::Value::Array(v) => {
                Self::Array(v.into_iter().map(Self::from_json).collect())
            }
            serde_json::Value::Object(v) => Self::Object(v),
        }
    }

    pub fn to_json(&self) -> serde_json::Value {
        match self {
            Self::Null => serde_json::Value::Null,
            Self::Bool(v) => serde_json::Value::Bool(*v),
            Self::Number(v) => serde_json::Number::from_f64(*v)
                .map_or(serde_json::Value::Null, serde_json::Value::Number),
            Self::String(v) => serde_json::Value::String(v.clone()),
            Self::Array(v) => serde_json::Value::Array(v.iter().map(Self::to_json).collect()),
            Self::Object(v) => serde_json::Value::Object(v.clone()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Subscript {
    Number(f64),
    String(String),
}

impl PartialEq for Subscript {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Number(a), Self::Number(b)) => a.to_bits() == b.to_bits(),
            (Self::String(a), Self::String(b)) => a == b,
            _ => false,
        }
    }
}

impl Eq for Subscript {}

impl std::hash::Hash for Subscript {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        match self {
            Self::Number(v) => {
                1u8.hash(state);
                v.to_bits().hash(state);
            }
            Self::String(v) => {
                2u8.hash(state);
                v.hash(state);
            }
        }
    }
}

impl Subscript {
    pub fn from_value(value: Value) -> Self {
        match value {
            Value::Number(v) => Self::Number(v),
            other => Self::String(other.as_string()),
        }
    }

    pub fn to_value(&self) -> Value {
        match self {
            Self::Number(v) => Value::Number(*v),
            Self::String(v) => Value::String(v.clone()),
        }
    }

    pub fn canonical_cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (Self::Number(a), Self::Number(b)) => a.total_cmp(b),
            (Self::Number(_), Self::String(_)) => Ordering::Less,
            (Self::String(_), Self::Number(_)) => Ordering::Greater,
            (Self::String(a), Self::String(b)) => a.as_bytes().cmp(b.as_bytes()),
        }
    }
}
