const { contextBridge } = require('electron');

contextBridge.executeInMainWorld({
  func: () => {
    const drop = (proto, name) => {
      try {
        if (proto && Object.prototype.hasOwnProperty.call(proto, name)) delete proto[name];
      } catch {}
    };
    drop(Navigator.prototype, 'connection');
    drop(Navigator.prototype, 'deviceMemory');
    drop(Navigator.prototype, 'hardwareConcurrency');
    drop(Navigator.prototype, 'getBattery');
    if (typeof NavigatorUAData === 'function') {
      const low = NavigatorUAData.prototype.toJSON;
      try {
        Object.defineProperty(NavigatorUAData.prototype, 'getHighEntropyValues', {
          value: function getHighEntropyValues() {
            const base = typeof low === 'function' ? low.call(this) : {};
            return Promise.resolve({ brands: base.brands, mobile: base.mobile, platform: base.platform });
          },
          writable: false,
          configurable: false,
        });
      } catch {}
    }
  },
});
