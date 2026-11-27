const { chromium } = require('/opt/npm-tools/node_modules/playwright');
const fs=require('fs');
let src=fs.readFileSync('../index.html','utf8').replace('https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js','three.min.js');
src=src.replace("const M700N=buildModel(specN700('noz')),M700K=buildModel(specN700('kyu'));","const M700N=buildModel(specN700('noz')),M700K=buildModel(specN700('kyu'));window.__M={M700K,M700N};");
fs.writeFileSync('./ortho.html',src);
(async()=>{
 const b=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
 const p=await b.newPage({viewport:{width:800,height:500}});p.on('pageerror',e=>console.log('PAGEERR',e.message));
 await p.goto('file://./ortho.html#offline');await p.waitForTimeout(4000);
 const PPM=60;
 const shots=await p.evaluate((PPM)=>{const M=window.__M.M700K,L=27,out={};
  const geo=M.carGeo(L,true,false),S=M.carLines(L,true,false,null);
  const lg=new THREE.BufferGeometry();lg.setAttribute('position',new THREE.Float32BufferAttribute(S.p,3));
  const sc=new THREE.Scene();sc.background=new THREE.Color(0xffffff);
  const occ=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({color:0xe9e7e2,polygonOffset:true,polygonOffsetFactor:2,polygonOffsetUnits:4,side:THREE.DoubleSide}));sc.add(occ);
  const ln=new THREE.LineSegments(lg,new THREE.LineBasicMaterial({color:0x202020}));sc.add(ln);
  const ed=new THREE.LineSegments(new THREE.EdgesGeometry(geo,35),new THREE.LineBasicMaterial({color:0x707070}));sc.add(ed);
  const tip=L/2;
  const views={side:{w:15.4,h:4.6,pos:[tip-7.3,1.9,-50],up:[0,1,0],look:[tip-7.3,1.9,0]},plan:{w:15.4,h:4.2,pos:[tip-7.3,50,0],up:[0,0,1],look:[tip-7.3,0,0]},front:{w:4.4,h:4.4,pos:[50,1.95,0],up:[0,1,0],look:[0,1.95,0]}};
  for(const [n,v] of Object.entries(views)){const W=Math.round(v.w*PPM),H=Math.round(v.h*PPM),c=document.createElement('canvas');c.width=W;c.height=H;
   const r=new THREE.WebGLRenderer({canvas:c,antialias:true,preserveDrawingBuffer:true});r.setSize(W,H,false);
   const cam=new THREE.OrthographicCamera(-v.w/2,v.w/2,v.h/2,-v.h/2,.1,200);cam.position.set(...v.pos);cam.up.set(...v.up);cam.lookAt(...v.look);
   r.render(sc,cam);out[n]=c.toDataURL('image/png');}
  return out;},PPM);
 for(const [n,d] of Object.entries(shots))fs.writeFileSync(`./o_${n}.png`,Buffer.from(d.split(',')[1],'base64'));
 await b.close();})();
