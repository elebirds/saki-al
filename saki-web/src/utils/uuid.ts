/**
 * 生成 UUID v4 格式的字符串
 * 优先使用 crypto.randomUUID()（需要安全上下文/HTTPS）
 * 如果不可用，则降级使用 crypto.getRandomValues() 生成
 * 
 * @returns UUID v4 格式的字符串
 */
export function generateUUID(): string {
  // 优先使用 crypto.randomUUID()（如果可用）
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    try {
      return crypto.randomUUID();
    } catch (e) {
      // 如果调用失败（例如在非安全上下文中），降级到手动实现
    }
  }

  // 降级实现：使用 crypto.getRandomValues() 生成 UUID v4
  // UUID v4 格式：xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
  // 其中 x 是任意十六进制数字，y 是 8、9、A 或 B 之一
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);

  // 设置版本号（第 6-7 位为 0100，表示版本 4）
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  // 设置变体（第 8-9 位为 10xx）
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  // 转换为十六进制字符串并格式化
  const hex = Array.from(bytes)
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');

  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32)
  ].join('-');
}






