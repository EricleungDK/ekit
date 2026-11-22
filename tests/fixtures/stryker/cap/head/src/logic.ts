export function pos(n: number): boolean {
  return n > 0;
}
export const label = (a: number, b: number) => `${a} is ${a > b ? 'big' : 'small'}`;
export const v = (x: boolean) => x ? 1 : 2;
export const either = (a?: string, b?: string) => a ?? b;
export const neg = -1;
export const arr = [1, 2, 3];
export const say = 'say "hi" now';
