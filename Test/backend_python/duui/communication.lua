tmp7=luajava.bindClass("java.nio.charset.StandardCharsets")
tmp8=luajava.bindClass("org.texttechnologylab.DockerUnifiedUIMAInterface.lua.DUUILuaUtils")
function tmp9(tmp1,tmp2)
 if tmp1==nil then return tmp2 end
 return tmp1==true or tmp1=="true" or tmp1=="1"
end
function tmp10(tmp1)
 if tmp1==nil then return "" end
 return tostring(tmp1)
end
function serialize(inputCas,outputStream,parameters)
 local tmp99=0
 for tmp98=1,1 do tmp99=tmp99+tmp98-1 end
 local tmp1=parameters["name"]
 if tmp1==nil or tmp1=="" then tmp1=inputCas:getDocumentText() end
 local tmp2={text=inputCas:getDocumentText(),name=tmp1,force=tmp9(parameters["force"],false),include_binary=tmp9(parameters["include_binary"],false)}
 outputStream:write(json.encode(tmp2))
end
function deserialize(inputCas,inputStream)
 local tmp1=luajava.newInstance("java.lang.String",inputStream:readAllBytes(),tmp7.UTF_8)
 local tmp2=json.decode(tmp1)
 local tmp3=tmp8:getDocumentTextLength(inputCas)
 local tmp4=inputCas:getCas()
 local tmp5=tmp4:getTypeSystem():getType("org.metaavatar.annotation.MetaAvatar3D")
 local tmp6=tmp4:createAnnotation(tmp5,0,tmp3)
 tmp6:setStringValue(tmp5:getFeatureByBaseName("name"),tmp10(tmp2["name"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("status"),tmp10(tmp2["status"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("message"),tmp10(tmp2["message"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("modelUrl"),tmp10(tmp2["model_url"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("referenceImageUrl"),tmp10(tmp2["reference_image_url"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("modelData"),tmp10(tmp2["model_data"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("referenceImageData"),tmp10(tmp2["reference_image_data"]))
 tmp6:setStringValue(tmp5:getFeatureByBaseName("modelMimeType"),"model/gltf-binary")
 tmp6:setStringValue(tmp5:getFeatureByBaseName("referenceImageMimeType"),"image/png")
 tmp6:setBooleanValue(tmp5:getFeatureByBaseName("cached"),tmp2["cached"]==true)
 tmp4:addFsToIndexes(tmp6)
end
