#!/usr/bin/env node
/**
 * dl4henga — 四站下载工具 CLI 入口 (npx 兼容)
 *
 * 检测 Python 环境，转发所有参数到 dl.py
 *
 * 用法:
 *   npx dl4henga search "毛玉牛乳"
 *   npx dl4henga --check
 *   npx dl4henga 604256
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// ── 找到 scripts 目录 ────────────────────────────────────
function findScriptsDir() {
    // 1. 开发模式: cli.js 和 scripts/ 在同一目录
    const devDir = path.join(__dirname, 'scripts');
    if (fs.existsSync(path.join(devDir, 'dl.py'))) {
        return devDir;
    }

    // 2. 全局安装: ../lib/node_modules/dl4henga/scripts
    const globalDir = path.join(__dirname, '..', 'scripts');
    if (fs.existsSync(path.join(globalDir, 'dl.py'))) {
        return globalDir;
    }

    // 3. npx 缓存: ../../dl4henga/scripts
    const npxDir = path.join(__dirname, '..', '..', 'scripts');
    if (fs.existsSync(path.join(npxDir, 'dl.py'))) {
        return npxDir;
    }

    return null;
}

// ── 检测 Python ──────────────────────────────────────────
function findPython() {
    const candidates = ['python3', 'python'];
    for (const py of candidates) {
        try {
            const result = require('child_process').spawnSync(py, ['--version']);
            if (result.status === 0) {
                // 验证版本 >= 3.8
                const ver = result.stderr.toString() + result.stdout.toString();
                const match = ver.match(/Python\s+(\d+)\.(\d+)/);
                if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 8) {
                    return py;
                }
            }
        } catch (_) {}
    }
    return null;
}

// ── 主入口 ───────────────────────────────────────────────
const scriptsDir = findScriptsDir();
if (!scriptsDir) {
    console.error('❌ 找不到 dl4henga 脚本目录');
    console.error('   请确认已正确安装: npm install -g dl4henga');
    process.exit(1);
}

const python = findPython();
if (!python) {
    console.error('❌ 未找到 Python 3.8+ 环境');
    console.error('   请安装: brew install python3');
    process.exit(1);
}

const dlPy = path.join(scriptsDir, 'dl.py');
if (!fs.existsSync(dlPy)) {
    console.error(`❌ 找不到入口脚本: ${dlPy}`);
    process.exit(1);
}

// 转发所有参数到 dl.py
const args = process.argv.slice(2);
const child = spawn(python, [dlPy, ...args], {
    stdio: 'inherit',
    env: { ...process.env },
});

child.on('close', (code) => {
    process.exit(code);
});
