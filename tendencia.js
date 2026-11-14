(function(){
var L=[],cat="",D="";
var brl=new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL"});
function el(t,c,x){var n=document.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n}
function ok(u){return /^https?:\/\//i.test(u||"")?u:""}
function chips(){
var bx=document.getElementById("chips");bx.innerHTML="";
var cs=[""];L.forEach(function(p){if(cs.indexOf(p.categoria)<0)cs.push(p.categoria)});
cs.forEach(function(c){
var b=el("button","chip"+(c===cat?" on":""),c||"Tudo");b.type="button";
b.onclick=function(){cat=c;chips();draw()};bx.appendChild(b)})}
function draw(){
var g=document.getElementById("grid");g.innerHTML="";
var v=L.filter(function(p){return !cat||p.categoria===cat});
v.sort(function(a,b){return b.desconto-a.desconto});
document.getElementById("count").textContent=v.length+" produtos";
if(!v.length){g.appendChild(el("p","empty","Nenhum produto por enquanto."));return}
v.forEach(function(p){
var c=el("article","card"),h=ok(p.link),f=ok(p.foto);
if(f){var i=el("img");i.src=f;i.alt="";c.appendChild(i)}
c.appendChild(el("span","off","-"+p.desconto+"%"));
var b=el("div","cb");
b.appendChild(el("div","st",p.categoria+" · "+p.loja));
b.appendChild(el("div","nm",p.nome));
b.appendChild(el("div","pr",brl.format(p.preco)));
b.appendChild(el("div","nt","Preço visto em "+D+". Confira na loja."));
if(h){var a=el("a","btn","Ver oferta");a.href=h;a.target="_blank";a.rel="noopener noreferrer sponsored nofollow";b.appendChild(a)}
c.appendChild(b);g.appendChild(c)})}
fetch("tendencia.json?v="+Date.now()).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){L=d.produtos||[];D=(d.atualizado||"").slice(0,5);chips();draw()}).catch(function(){document.getElementById("count").textContent="Não consegui carregar os produtos agora."})
})();
