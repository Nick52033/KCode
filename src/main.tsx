import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ToastProvider } from "./components/Toast";
import { finishBoot, installBootFallback } from "./lib/boot";
import { migrateLegacyStorageKeys } from "./lib/storageMigration";
import "./styles/workspace.css";

// 旧版 k-coder 的 kcoder_ 键一次性迁移到 kcode_，必须在 App 读取 localStorage 之前执行。
migrateLegacyStorageKeys();
installBootFallback();

const container = document.getElementById("root") as HTMLElement;

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
);

// 等首帧真正绘制出来再收起启动屏、显示主窗口（双 rAF：第一次提交后，第二次确认已上屏）。
requestAnimationFrame(() => requestAnimationFrame(finishBoot));
