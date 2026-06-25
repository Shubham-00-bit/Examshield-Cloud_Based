
# 🛡️ ExamShield — Blockchain-Based Paper Leakage Prevention System

> **Preventing exam paper leaks using the power of decentralized blockchain technology.**  
> Inspired by real-world incidents like the NEET 2024 paper leak, ExamShield ensures tamper-proof, secure, and transparent exam paper management.

---

## 📌 Table of Contents

- [About the Project](#about-the-project)
- [The Problem](#the-problem)
- [Our Solution](#our-solution)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [How It Works](#how-it-works)
- [Screenshots](#screenshots)
- [Future Scope](#future-scope)
- [Contributors](#contributors)
- [License](#license)

---

## 📖 About the Project

**ExamShield** is a final year engineering project that leverages **blockchain technology** to prevent the unauthorized access, tampering, and leaking of examination papers. The system ensures that exam papers are encrypted, stored securely on a decentralized blockchain, and can only be accessed by authorized personnel at the right time.

---

## ❌ The Problem

Paper leakage in competitive exams (like NEET, JEE, UPSC, etc.) has become a serious national issue:

- 🔓 Centralized systems are vulnerable to insider threats
- 📄 Papers can be copied, modified, or distributed before exams
- 🕵️ No audit trail to trace who accessed the paper
- ⚖️ Students lose years of hard work due to corruption

---

## ✅ Our Solution

ExamShield uses **blockchain** to create a system where:

- Exam papers are **encrypted and hashed** before storage
- Data is stored on a **decentralized, immutable ledger**
- Access is controlled by **smart contracts** — no human override
- Every action is **logged with a timestamp** for full transparency
- Papers are **automatically released** only at the scheduled exam time

---

## ✨ Key Features

| Feature | Description |
|--------|-------------|
| 🔐 End-to-End Encryption | Papers are AES-encrypted before being uploaded |
| ⛓️ Blockchain Storage | Immutable, tamper-proof storage using Ethereum |
| 📜 Smart Contracts | Access control governed entirely by code |
| 🕒 Time-Locked Release | Papers auto-unlock only at the scheduled exam time |
| 🧾 Audit Trail | Every access attempt is permanently logged on-chain |
| 👤 Role-Based Access | Separate roles for Admin, Examiner, and Invigilator |
| 🚨 Tamper Detection | Any modification attempt is instantly detected |

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Frontend (Web UI)                │
│              (React.js / HTML + CSS + JS)               │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                   Backend / API Layer                   │
│                   (Node.js / Python)                    │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
┌───────▼────────┐             ┌────────▼────────┐
│  Smart Contract │             │  IPFS / File    │
│  (Solidity on  │             │  Storage System │
│   Ethereum)    │             │                 │
└────────────────┘             └─────────────────┘
        │
┌───────▼────────────────────────────────────────────────┐
│            Blockchain Network (Ethereum / Ganache)     │
└────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Blockchain | Ethereum (Ganache for local testing) |
| Smart Contracts | Solidity |
| Frontend | React.js / HTML, CSS, JavaScript |
| Backend | Node.js / Python Flask |
| Web3 Integration | Web3.js / Ethers.js |
| Storage | IPFS (InterPlanetary File System) |
| Encryption | AES-256 |
| IDE | Remix IDE, VS Code |

---

## 🚀 Getting Started

### Prerequisites

- Node.js (v16+)
- npm or yarn
- Ganache (local blockchain)
- MetaMask browser extension
- Truffle Framework

### Installation

```bash
# Clone the repository
git clone https://github.com/chetanS911/ExamShield-Blockchain-Based-Paper-Leakage-Prevention.git

# Navigate to the project directory
cd ExamShield-Blockchain-Based-Paper-Leakage-Prevention

# Install dependencies
npm install

# Compile smart contracts
truffle compile

# Deploy contracts to local blockchain (Ganache)
truffle migrate --network development

# Start the frontend
npm start
```

---

## ⚙️ How It Works

1. **Admin uploads the exam paper** → paper is encrypted using AES-256
2. **Encrypted paper is hashed** using SHA-256 and stored on IPFS
3. **Hash is recorded on blockchain** via a smart contract with a time lock
4. **Smart contract enforces access rules** — no one can retrieve the paper before exam time
5. **At exam time**, the smart contract automatically allows authorized users to decrypt and access the paper
6. **Every access event** is permanently logged on the blockchain with a timestamp

---


## 🔮 Future Scope

- 📱 Mobile app for invigilators
- 🤖 AI-based anomaly detection for suspicious access patterns
- 🌐 Integration with NTA / CBSE systems
- 🗳️ Multi-signature approval for paper upload
- 📊 Real-time monitoring dashboard for exam boards

---






