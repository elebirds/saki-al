/**
 * 安全工具函数
 * 用于在前端对密码进行哈希处理，避免明文传输
 */

/**
 * 使用 SHA-256 对密码进行哈希
 * @param password 原始密码
 * @returns 哈希后的密码（十六进制字符串）
 */
export async function hashPassword(password: string): Promise<string> {
  // 使用 Web Crypto API 进行 SHA-256 哈希
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  
  // 将 ArrayBuffer 转换为十六进制字符串
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  
  return hashHex;
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
 * 在生产环境强制使用 HTTPS
 * 如果不是 HTTPS，会抛出错误
 */
export function enforceHttps(): void {
  if (isProduction() && !isHttps()) {
    throw new Error('生产环境必须使用 HTTPS 协议以确保安全');
  }
}

