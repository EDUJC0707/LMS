const path=require("path");
const {chromium}=require(path.join(__dirname,"..","test","rpa-test","node_modules","playwright"));
const sites=[
  ["channeltalk","https://channel.io/ko"],
  ["vdocipher","https://www.vdocipher.com/"],
  ["mux","https://www.mux.com/"],
  ["meet","https://workspace.google.com/products/meet/"],
];
(async()=>{
  const b=await chromium.launch();
  const ctx=await b.newContext({viewport:{width:1440,height:900},deviceScaleFactor:2});
  const p=await ctx.newPage();
  for(const [name,url] of sites){
    try{
      await p.goto(url,{waitUntil:"domcontentloaded",timeout:30000});
      await p.waitForTimeout(3500);
      await p.screenshot({path:path.join(__dirname,"assets",`shot-${name}.png`)});
      console.log("ok",name);
    }catch(e){console.log("FAIL",name,e.message.slice(0,60));}
  }
  await b.close();
})();
