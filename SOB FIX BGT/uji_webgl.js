// Uji render WebGL sungguhan (opsional). Butuh Linux dengan layar virtual:
//   npm install jsdom gl
//   xvfb-run -a -s "-screen 0 1280x1024x24 +extension GLX +render" node uji_webgl.js viva-mpc-simulator.html hasil.png [yaw] [xray]
// Menulis PNG dari piksel yang benar-benar digambar shader, jadi tampilannya bisa dinilai tanpa peramban.
// Menjalankan halaman di jsdom, tetapi kanvas #lungGL diberi konteks WebGL sungguhan
// (headless-gl / ANGLE). Hasil render dibaca balik lalu ditulis sebagai PNG.
const fs=require('fs'), zlib=require('zlib'), {JSDOM}=require('jsdom'), createGL=require('gl');
const html=fs.readFileSync(process.argv[2],'utf8');
const OUT=process.argv[3]||'/tmp/webtest/gl.png';
const YAW=process.argv[4]!==undefined?parseFloat(process.argv[4]):null;
const XRAY=process.argv[5]==='xray';
const CW=640, CH=470, DPR=2;
const W=CW*DPR, H=CH*DPR;
let GLCTX=null; const logs=[];
function ctx2d(){const noop=()=>{};return new Proxy({setTransform:noop,clearRect:noop,beginPath:noop,moveTo:noop,
  lineTo:noop,arc:noop,stroke:noop,fill:noop,fillText:noop,save:noop,restore:noop,translate:noop,rotate:noop,scale:noop,
  closePath:noop,fillRect:noop,strokeRect:noop,setLineDash:noop,measureText:t=>({width:String(t).length*5.5}),
  createRadialGradient:()=>({addColorStop:noop}),createLinearGradient:()=>({addColorStop:noop})},
  {get:(t,k)=>k in t?t[k]:undefined,set:(t,k,v)=>{t[k]=v;return true;}});}
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
  w.devicePixelRatio=DPR;
  // headless-gl mengenali typed array dengan instanceof terhadap konstruktor Node.
  // Skrip halaman berjalan di realm jsdom yang punya konstruktor sendiri, jadi
  // disamakan di sini. Di peramban hanya ada satu realm; ini murni urusan harness.
  for(const k of ['Uint8Array','Uint8ClampedArray','Int8Array','Uint16Array','Int16Array',
                  'Uint32Array','Int32Array','Float32Array','Float64Array','ArrayBuffer','DataView'])
    w[k]=globalThis[k];
  w.HTMLCanvasElement.prototype.getContext=function(type){
    if(this.id==='lungGL'&&(type==='webgl'||type==='experimental-webgl')){
      if(!GLCTX) GLCTX=createGL(W,H,{antialias:true,alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true});
      return GLCTX;
    }
    if(type!=='2d') return null;
    if(!this.__c) this.__c=ctx2d(); return this.__c;
  };
  w.HTMLCanvasElement.prototype.getBoundingClientRect=()=>({width:CW,height:CH,top:0,left:0,right:CW,bottom:CH});
  w.console.warn=(...a)=>logs.push('warn: '+a.join(' '));
  w.console.error=(...a)=>logs.push('error: '+a.join(' '));
  w.addEventListener('error',e=>logs.push('error: '+(e.error?e.error.message:e.message)));
}});
const w=dom.window;
setTimeout(()=>{
  const d=w.document;
  console.log('mode render :', d.getElementById('rmode').textContent);
  if(XRAY) d.getElementById('btnXray').dispatchEvent(new w.Event('click'));
  if(YAW!==null){ w.eval('CAM.yaw='+YAW); }
  setTimeout(()=>{
    logs.forEach(l=>console.log(l));
    if(!GLCTX){console.log('TIDAK ADA KONTEKS GL'); process.exit(1);}
    const gl=GLCTX, px=new Uint8Array(W*H*4);
    gl.readPixels(0,0,W,H,gl.RGBA,gl.UNSIGNED_BYTE,px);
    // latar panggung seperti CSS, lalu piksel GL (premultiplied) di atasnya
    const img=Buffer.alloc(W*H*3); let cov=0;
    for(let y=0;y<H;y++)for(let x=0;x<W;x++){
      const dx=(x-W*0.5)/(W*1.15*0.5), dy=(y-H*0.22)/(H*0.95);
      const t=Math.min(1,Math.hypot(dx,dy));
      const bg = t<0.55 ? [251+(230-251)*t/0.55, 251+(232-251)*t/0.55, 250+(233-250)*t/0.55]
                        : [230+(207-230)*(t-0.55)/0.45, 232+(212-232)*(t-0.55)/0.45, 233+(215-233)*(t-0.55)/0.45];
      const si=((H-1-y)*W+x)*4, a=px[si+3]/255; if(a>0.02) cov++;
      const o=(y*W+x)*3;
      for(let c=0;c<3;c++) img[o+c]=Math.round(px[si+c]+bg[c]*(1-a));
    }
    const raw=Buffer.alloc((W*3+1)*H);
    for(let y=0;y<H;y++){raw[y*(W*3+1)]=0; img.copy(raw,y*(W*3+1)+1,y*W*3,(y+1)*W*3);}
    let T=null;const crc=b=>{if(!T){T=new Int32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;T[n]=c;}}
      let c=-1;for(const x of b)c=T[(c^x)&255]^(c>>>8);return c^-1;};
    const ch=(t,dd)=>{const l=Buffer.alloc(4);l.writeUInt32BE(dd.length);const td=Buffer.concat([Buffer.from(t),dd]);
      const c=Buffer.alloc(4);c.writeUInt32BE(crc(td)>>>0);return Buffer.concat([l,td,c]);};
    const ih=Buffer.alloc(13);ih.writeUInt32BE(W,0);ih.writeUInt32BE(H,4);ih[8]=8;ih[9]=2;
    fs.writeFileSync(OUT,Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),ch('IHDR',ih),
      ch('IDAT',zlib.deflateSync(raw,{level:6})),ch('IEND',Buffer.alloc(0))]));
    console.log('piksel tertutup GL:', (100*cov/(W*H)).toFixed(1)+'%', ' galat GL:', gl.getError());
    process.exit(0);
  },1500);
},800);
