const path=require("path");
const {chromium}=require(path.join(__dirname,"..","test","rpa-test","node_modules","playwright"));
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:794,height:1123},deviceScaleFactor:2});
await p.goto("file://"+path.join(__dirname,"report.html"),{waitUntil:"networkidle"});await p.waitForTimeout(500);
const pages=await p.$$(".page");
for(let i=0;i<pages.length;i++){await pages[i].screenshot({path:path.join(__dirname,`qa-${i+1}.png`)});}
await b.close();console.log("qa done",pages.length);})();
