/**
 * 安全工具函数
 * 用于在前端对密码进行哈希处理，避免明文传输
 */

// ============================================================================
// SHA-256 纯 JavaScript 实现（降级方案）
// ============================================================================

/**
 * 纯 JavaScript 实现的 SHA-256 哈希函数
 * 当 Web Crypto API 不可用时作为降级方案
 */
function sha256Fallback(message: string): string {
    // SHA-256 常量
    const K = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    ];

    // 辅助函数
    const rightRotate = (value: number, amount: number): number => {
        return (value >>> amount) | (value << (32 - amount));
    };

    // 将字符串转换为字节数组
    const utf8Encode = (str: string): number[] => {
        const bytes: number[] = [];
        for (let i = 0; i < str.length; i++) {
            const charCode = str.charCodeAt(i);
            if (charCode < 0x80) {
                bytes.push(charCode);
            } else if (charCode < 0x800) {
                bytes.push(0xc0 | (charCode >> 6));
                bytes.push(0x80 | (charCode & 0x3f));
            } else if (charCode < 0xd800 || charCode >= 0xe000) {
                bytes.push(0xe0 | (charCode >> 12));
                bytes.push(0x80 | ((charCode >> 6) & 0x3f));
                bytes.push(0x80 | (charCode & 0x3f));
            } else {
                i++;
                const charCode2 = str.charCodeAt(i);
                const codePoint = 0x10000 + (((charCode & 0x3ff) << 10) | (charCode2 & 0x3ff));
                bytes.push(0xf0 | (codePoint >> 18));
                bytes.push(0x80 | ((codePoint >> 12) & 0x3f));
                bytes.push(0x80 | ((codePoint >> 6) & 0x3f));
                bytes.push(0x80 | (codePoint & 0x3f));
            }
        }
        return bytes;
    };

    // 预处理消息
    const msg = utf8Encode(message);
    const msgLen = msg.length * 8;

    // 添加填充
    msg.push(0x80);
    while ((msg.length % 64) !== 56) {
        msg.push(0x00);
    }

    // 添加长度（64位，大端序）
    const lengthBytes: number[] = [];
    let temp = msgLen;
    for (let i = 0; i < 8; i++) {
        lengthBytes.push(temp & 0xff);
        temp = temp >>> 8;
    }
    msg.push(...lengthBytes.reverse());

    // 初始化哈希值
    let h0 = 0x6a09e667;
    let h1 = 0xbb67ae85;
    let h2 = 0x3c6ef372;
    let h3 = 0xa54ff53a;
    let h4 = 0x510e527f;
    let h5 = 0x9b05688c;
    let h6 = 0x1f83d9ab;
    let h7 = 0x5be0cd19;

    // 处理每个 512 位块
    for (let chunkStart = 0; chunkStart < msg.length; chunkStart += 64) {
        const w: number[] = new Array(64);

        // 将块分解为 16 个 32 位字
        for (let i = 0; i < 16; i++) {
            w[i] = (msg[chunkStart + i * 4] << 24) |
                (msg[chunkStart + i * 4 + 1] << 16) |
                (msg[chunkStart + i * 4 + 2] << 8) |
                (msg[chunkStart + i * 4 + 3]);
        }

        // 扩展为 64 个字
        for (let i = 16; i < 64; i++) {
            const s0 = rightRotate(w[i - 15], 7) ^ rightRotate(w[i - 15], 18) ^ (w[i - 15] >>> 3);
            const s1 = rightRotate(w[i - 2], 17) ^ rightRotate(w[i - 2], 19) ^ (w[i - 2] >>> 10);
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
        }

        // 初始化工作变量
        let a = h0;
        let b = h1;
        let c = h2;
        let d = h3;
        let e = h4;
        let f = h5;
        let g = h6;
        let h = h7;

        // 主循环
        for (let i = 0; i < 64; i++) {
            const S1 = rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25);
            const ch = (e & f) ^ ((~e) & g);
            const temp1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
            const S0 = rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22);
            const maj = (a & b) ^ (a & c) ^ (b & c);
            const temp2 = (S0 + maj) >>> 0;

            h = g;
            g = f;
            f = e;
            e = (d + temp1) >>> 0;
            d = c;
            c = b;
            b = a;
            a = (temp1 + temp2) >>> 0;
        }

        // 添加到哈希值
        h0 = (h0 + a) >>> 0;
        h1 = (h1 + b) >>> 0;
        h2 = (h2 + c) >>> 0;
        h3 = (h3 + d) >>> 0;
        h4 = (h4 + e) >>> 0;
        h5 = (h5 + f) >>> 0;
        h6 = (h6 + g) >>> 0;
        h7 = (h7 + h) >>> 0;
    }

    // 生成最终的哈希值（十六进制字符串）
    const hashArray = [h0, h1, h2, h3, h4, h5, h6, h7];
    return hashArray.map(val => {
        let hex = val.toString(16);
        while (hex.length < 8) {
            hex = '0' + hex;
        }
        return hex;
    }).join('');
}

// ============================================================================
// 主要 API
// ============================================================================

/**
 * 使用 SHA-256 对密码进行哈希
 * 优先使用 Web Crypto API，如果不可用则降级到纯 JavaScript 实现
 * @param password 原始密码
 * @returns 哈希后的密码（十六进制字符串）
 */
export async function hashPassword(password: string): Promise<string> {
    // 获取 crypto 对象（支持浏览器和 worker 环境）
    const cryptoObj = typeof window !== 'undefined'
        ? window.crypto
        : typeof self !== 'undefined'
            ? self.crypto
            : (typeof globalThis !== 'undefined' ? globalThis.crypto : undefined);

    // 检查 crypto.subtle 是否可用
    if (cryptoObj && cryptoObj.subtle) {
        try {
            // 优先使用 Web Crypto API（更快、更安全）
            const encoder = new TextEncoder();
            const data = encoder.encode(password);
            const hashBuffer = await cryptoObj.subtle.digest('SHA-256', data);

            // 将 ArrayBuffer 转换为十六进制字符串
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

            return hashHex;
        } catch (error: any) {
            // 如果 Web Crypto API 失败，降级到纯 JavaScript 实现
            console.warn('Web Crypto API 不可用，使用降级方案进行密码哈希');
            return sha256Fallback(password);
        }
    }

    // crypto.subtle 不可用，使用降级方案
    console.warn('Web Crypto API 不可用，使用降级方案进行密码哈希');
    return sha256Fallback(password);
}

/**
 * 检查当前是否使用 HTTPS
 * @returns 如果使用 HTTPS 返回 true，否则返回 false
 */
export function isHttps(): boolean {
    if (typeof window === 'undefined') {
        return false;
    }
    return window.location.protocol === 'https:';
}

/**
 * 检查是否为生产环境
 * @returns 如果是生产环境返回 true，否则返回 false
 */
export function isProduction(): boolean {
    if (typeof window === 'undefined') {
        // 在非浏览器环境中，默认不是生产环境
        return false;
    }
    // 通过 hostname 判断是否为生产环境
    // 生产环境通常不是 localhost、127.0.0.1 或内网 IP
    return window.location.hostname !== 'localhost' &&
        window.location.hostname !== '127.0.0.1' &&
        !window.location.hostname.startsWith('192.168.') &&
        !window.location.hostname.startsWith('10.');
}

/**
 * 根据环境变量强制使用 HTTPS
 * 只有当 VITE_FORCE_HTTPS 环境变量存在且为 'true' 时才会强制使用 HTTPS
 * 如果不是 HTTPS，会抛出错误
 */
export function enforceHttps(): void {
    // 检查环境变量 VITE_FORCE_HTTPS 是否存在且为 'true'
    const forceHttps = import.meta.env.VITE_FORCE_HTTPS === 'true';

    if (forceHttps && !isHttps()) {
        throw new Error('必须使用 HTTPS 协议以确保安全');
    }
}

